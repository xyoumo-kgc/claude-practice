"""
FUSION-CORE v1.0 — 賢人のデイトレード × 100億円トレーダー 融合システムの参照実装（仕様: fusion/SPEC.md）

4時間足レベルの上昇（下降）構造の中で、押し（戻り）が 4H MA（1時間足の SMA80）に届き、4H MA が逆向きでないときに、
1時間足で「安値切上げを保ったまま戻り高値を上抜ける」瞬間を逆指値で取る。
損切りは切上げ安値の外。出口は「4Hレベルの新しい押し安値が確定するたびに損切りを引き上げる」と「週末・休場前の全決済」だけ。

H1 足だけで動く（上位足は期間を換算した MA とスイングの深さで表す: SMA80 = 4H 20MA、深さ12 = 4Hレベルの波）。
判定は確定足だけで行い、注文は次の足から有効（先読みなし）。約定は fusion/broker.py のモデルを使う。

  trades, funnel = run_h1(h1, 'EURUSD')                 # 既定構成（fusion）
  trades, funnel = run_h1(h1, 'EURUSD', VARIANTS['oku_only'])
  trades = run({'H1': h1, 'M15': m15}, 'EURUSD', variant='p2')   # evaluate.py から呼ぶ形
"""
import bisect
from datetime import date, timedelta

import numpy as np
import pandas as pd

from fusion import broker as bk
from fusion import indicators as ind

S_NOM = bk.NOMINAL_SPREAD                       # 名目スプレッド（SPEC §10.3）
SYMBOL_ORDER = ['EURUSD', 'GBPUSD', 'EURJPY', 'AUDUSD', 'USDCAD', 'AUDJPY', 'XAUUSD']   # 素朴ベースラインの乱数系列番号

# ---------------------------------------------------------------- パラメータ（SPEC §12）
CORE = dict(N_BIG=12, N_SMALL=3, ZONE_ATR=0.5, SLOPE_MIN=0.0, ENTRY_BUF_ATR=0.05, SL_BUF_ATR=0.2,
            R_MIN_ATR=0.8, R_MAX_ATR=3.0)
AUX = dict(N_D1=72, TOL_LV=0.6, TOL_S=1.0, CF_MIN_TOUCH=3, RR_CF=2.0, GAP_HI=8.0, LVL_MAX_ATR=3.0)
FIX = dict(SLOPE_LB=12, LB_SMALL=400, LB_BIG=3000, LB_D1=8000, L0_SEARCH=6, LV_WIN_BIG=1200, LV_WIN_D1=2880,
           SPREAD_FLOOR=3.0, CONV_ATR=0.5, TP1_MIN_R=1.0, TP_DEFAULT_R=2.0, GAP_FALLBACK_H=12,
           NAIVE_SL_ATR=1.5)

# スイッチの既定 = fusion（SPEC §12.5）
DEFAULT_SW = dict(
    g1='dow2', require_hh=True, g2=True, g3=False, place='touch',
    slope_gate=True, d1_gate='off', gap_gate=False, clear_gate=False, cf_scope='strong',
    support_gate=False, sl_mode='run', target_gate=0.0, h1_transition=False,
    entry='stop', one_fill=True, rollover=True, calendar=True, sl_floor=True, weekend=True, rcap=True,
    trail='big', partial=0.0, be=False, p3=False,
    naive_p=0.0, naive_seed=0,           # entry='naive'（素朴ベースライン）のときだけ使う
    warmup=None, expiry_emul=0,          # 照合専用（MinCore 試作の再現）。仕様の既定では使わない
)

# 事前登録した変種（SPEC §13）
VARIANTS = {
    'fusion': {},
    'oku_only': dict(place='conv', g2=False, d1_gate='strict', gap_gate=True, clear_gate=True,
                     cf_scope='strong', h1_transition=True, partial=0.5, trail='small'),
    'kenjin_only': dict(support_gate=True, sl_mode='node', target_gate=1.0, weekend=False, calendar=False),
    'mincore_final': dict(g3=True, slope_gate=False),
    'mincore_raw': dict(g3=True, slope_gate=False, calendar=False, one_fill=False, rollover=False, sl_floor=False,
                        warmup=600, expiry_emul=24),
    # 1要素ずつ外す
    'F-slope': dict(slope_gate=False), 'F-G2': dict(g2=False), 'F-HH': dict(require_hh=False),
    'F-stop': dict(entry='close'), 'F-trail': dict(trail='none'), 'F-weekend': dict(weekend=False, calendar=False),
    'F-slfloor': dict(sl_floor=False), 'F-onefill': dict(one_fill=False), 'F-rollover': dict(rollover=False),
    'F-calendar': dict(calendar=False), 'F-rcap': dict(rcap=False),
    # 1要素ずつ足す・置き換える
    'F+G3': dict(g3=True), 'F+d1': dict(d1_gate='strict'), 'F+d1soft': dict(d1_gate='soft'),
    'F+gap': dict(gap_gate=True), 'F+clear': dict(clear_gate=True, cf_scope='strong'),
    'F+clear_d1': dict(clear_gate=True, cf_scope='daily'), 'F+support': dict(support_gate=True),
    'F+slnode': dict(sl_mode='node'), 'F+partial': dict(partial=0.5), 'F+be': dict(partial=0.5, be=True),
    'F+trail1h': dict(trail='small'), 'F+p3': dict(p3=True), 'F~dowP': dict(g1='dowP'),
    'F+h1trans': dict(h1_transition=True), 'F~conv': dict(place='conv', g2=False),
}

# 感度（報告のみ。構成の選択には使わない）
SENSITIVITY = {
    'S:N_BIG=10': dict(N_BIG=10), 'S:N_BIG=16': dict(N_BIG=16),
    'S:N_SMALL=2': dict(N_SMALL=2), 'S:N_SMALL=4': dict(N_SMALL=4),
    'S:ZONE=0.25': dict(ZONE_ATR=0.25), 'S:ZONE=1.0': dict(ZONE_ATR=1.0),
    'S:R_MAX=2.5': dict(R_MAX_ATR=2.5), 'S:R_MAX=4.0': dict(R_MAX_ATR=4.0),
}


# ---------------------------------------------------------------- 暦（SPEC §2.6・付録C）
def easter(y):
    """復活祭（グレゴリオ暦）"""
    a = y % 19; b = y // 100; c = y % 100; d = b // 4; e = b % 4; f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i = c // 4; k = c % 4; l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451; month = (h + l_ - 7 * m + 114) // 31; day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def calendar_sets(sym, years):
    """(休場日 CAL_CLOSED, 早仕舞い日 CAL_EARLY)"""
    closed, early = set(), set()
    for y in years:
        closed |= {date(y, 12, 25), date(y, 1, 1)}
        early |= {date(y, 12, 24), date(y, 12, 31)}
        if sym == 'XAUUSD':
            closed.add(easter(y) - timedelta(days=2))                       # Good Friday
            nov1 = date(y, 11, 1)
            thu4 = nov1 + timedelta(days=(3 - nov1.weekday()) % 7 + 21)       # 11月第4木曜（感謝祭）
            early.add(thu4 + timedelta(days=1))                              # その翌金曜
            j4 = date(y, 7, 4)                                               # 独立記念日（土曜→前日、日曜→翌日）
            early.add(j4 - timedelta(days=1) if j4.weekday() == 5 else (j4 + timedelta(days=1) if j4.weekday() == 6 else j4))
    return closed, early


def next_weekday(dt):
    n = dt + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def time_rules(idx, sym, S, delta, gap_hours):
    """足ごとの時刻ルール（SPEC §2.6）: no_new（新規停止）・flat（全決済）・rollover・gap_before（休場明け）"""
    n = len(idx)
    ct = idx + delta
    hc = ct.hour.values + ct.minute.values / 60.0
    hc = np.where((hc == 0) & (ct.normalize() > idx.normalize()), 24.0, hc)   # 翌日0:00ちょうどの確定 → 24
    dates = [ts.date() for ts in idx]
    closed, early = calendar_sets(sym, range(idx[0].year, idx[-1].year + 2)) if n else (set(), set())
    no_new = np.zeros(n, bool); flat = np.zeros(n, bool); rollover = np.zeros(n, bool); gap_before = np.zeros(n, bool)
    for t in range(n):
        dt = dates[t]
        if S['calendar'] and dt in closed:
            no_new[t] = True; flat[t] = True
        elif S['calendar'] and dt in early:
            no_new[t] = hc[t] >= 17; flat[t] = hc[t] >= 19
        elif dt.weekday() == 4 or (S['calendar'] and next_weekday(dt) in closed):
            no_new[t] = hc[t] >= 20; flat[t] = hc[t] >= 22
        if not S['weekend']:
            flat[t] = False; no_new[t] = False               # 週末ルールごと外す（F-weekend・kenjin_only）
        rollover[t] = S['rollover'] and (hc[t] >= 23 or hc[t] < 1)
        if t > 0:
            gap_before[t] = (idx[t] - idx[t - 1] - delta) >= pd.Timedelta(hours=gap_hours)
    return no_new, flat, rollover, gap_before


# ---------------------------------------------------------------- 持続型ダウ状態機械（SPEC §5.3）
def dow_machine(H, L, C, depth):
    """T[k] ∈ {+1, 0, -1}、END[k]（終了の兆し）。足 k の確定時点の状態（因果的）。"""
    n = len(C)
    ih, il = ind.pivots(H, L, depth)
    T = np.zeros(n, dtype=int); END = np.zeros(n, dtype=int)
    sh, sl = [], []
    t_state = 0; pl_i = ph_i = -1; x = np.nan; endf = 0
    used_h, used_l = set(), set()
    for k in range(n):
        j = k - depth
        if j >= depth:
            if ih[j]:
                sh.append(j)
                if t_state == 1 and pl_i >= 0 and j > pl_i and H[j] < x:
                    endf = 1                                    # 上昇中の高値切下げ
            if il[j]:
                sl.append(j)
                if t_state == -1 and ph_i >= 0 and j > ph_i and L[j] > x:
                    endf = 1                                    # 下降中の安値切上げ
        if sh:
            hj = sh[-1]
            if hj not in used_h and C[k] > H[hj]:              # 直近確定高値の初回終値上抜け
                used_h.add(hj)
                a = hj + 1 + int(np.argmin(L[hj + 1:k + 1]))
                before = [s for s in sl if s < hj]
                if before and L[a] > L[before[-1]]:
                    t_state = 1; pl_i = a; x = float(np.max(H[a:k + 1])); endf = 0     # 安値切上げ＋高値更新
                elif t_state == -1:
                    t_state = 0; endf = 0                       # 下降の「終了」（転換ではない）
        if sl:
            lj = sl[-1]
            if lj not in used_l and C[k] < L[lj]:
                used_l.add(lj)
                a = lj + 1 + int(np.argmax(H[lj + 1:k + 1]))
                before = [s for s in sh if s < lj]
                if before and H[a] < H[before[-1]]:
                    t_state = -1; ph_i = a; x = float(np.min(L[a:k + 1])); endf = 0
                elif t_state == 1:
                    t_state = 0; endf = 0
        if t_state == 1:
            x = H[k] if np.isnan(x) else max(x, H[k])
        elif t_state == -1:
            x = L[k] if np.isnan(x) else min(x, L[k])
        T[k] = t_state; END[k] = endf
    return T, END


# ---------------------------------------------------------------- 節目エンジン（SPEC §6.2）
def cluster(points, tol):
    """points: [(price, 重み, ±1, 'B'|'D')]。先頭から tol 以内・クラスタ幅 2·tol 以内でまとめる"""
    if not points:
        return []
    pts = sorted(points, key=lambda p: p[0])
    groups, cur = [], [pts[0]]
    for p in pts[1:]:
        if p[0] - cur[0][0] <= 2 * tol and p[0] - cur[-1][0] <= tol:
            cur.append(p)
        else:
            groups.append(cur); cur = [p]
    groups.append(cur)
    return [{'price': float(np.median([q[0] for q in g])), 'touch': sum(q[1] for q in g),
             'nh': sum(1 for q in g if q[2] == 1), 'nl': sum(1 for q in g if q[2] == -1),
             'd1': any(q[3] == 'D' for q in g)} for g in groups]


# ---------------------------------------------------------------- 本体
def run_h1(h1, sym, sw=None, tf='H1', align=None):
    """h1: サーバー時間の OHLC（tf='M15' ならパターン②用の M15）。戻り値: (取引の辞書リスト, 理由コード別の件数)"""
    S = dict(DEFAULT_SW); S.update(sw or {})
    P = dict(CORE); P.update(AUX); P.update(FIX)
    P.update({k: v for k, v in S.items() if k in P})          # 感度用のパラメータ上書き
    s_nom = S_NOM[sym]
    O, H, L, C = (h1[k].to_numpy(dtype=float) for k in ('Open', 'High', 'Low', 'Close'))
    idx = h1.index; n = len(C)
    atr = ind.atr(H, L, C, 14)
    ma20, ma80, ma480 = ind.sma(C, 20), ind.sma(C, 80), ind.sma(C, 480)
    bs = ind.SwingBook(H, L, P['N_SMALL'], lookback=P['LB_SMALL'])
    bb = ind.SwingBook(H, L, P['N_BIG'], lookback=P['LB_BIG'])
    bd = ind.SwingBook(H, L, P['N_D1'], lookback=P['LB_D1'])
    TS, _ = dow_machine(H, L, C, P['N_SMALL'])
    TD, _ = dow_machine(H, L, C, P['N_D1'])
    br = bk.Broker(s_nom)
    delta = pd.Timedelta(hours=1) if tf == 'H1' else pd.Timedelta(minutes=15)
    no_new, flat, rollover, gap_before = time_rules(idx, sym, S, delta, P['GAP_FALLBACK_H'])
    rng = np.random.default_rng(S['naive_seed'] * 1000 + SYMBOL_ORDER.index(sym)) if S['entry'] == 'naive' else None
    funnel = {}

    def rej(code):
        funnel[code] = funnel.get(code, 0) + 1
        return None

    def levels_at(t):
        pts = []
        for book, ma, win, w, tag in ((bb, ma80, P['LV_WIN_BIG'], 1, 'B'), (bd, ma480, P['LV_WIN_D1'], 2, 'D')):
            lo = t - win + 1; hi = t - book.depth
            for arr, kind in ((book.h_idx, 1), (book.l_idx, -1)):
                a = bisect.bisect_left(arr, lo); b = bisect.bisect_right(arr, hi)
                for j in arr[a:b]:
                    if np.isnan(ma[j]):
                        continue
                    if kind == 1 and H[j] > ma[j]:              # 20MA の「山」だけ
                        pts.append((H[j], w, 1, tag))
                    if kind == -1 and L[j] < ma[j]:             # 「谷」だけ
                        pts.append((L[j], w, -1, tag))
        return cluster(pts, P['TOL_LV'] * atr[t])

    def g1_dow2(t, d, book, need_hh=True):
        """G1: 直近2つの高値・安値の切上げ（切下げ）＋終値が押し安値より上。成立なら押しの起点 j_peak"""
        bh, bl = book.highs(t, 2), book.lows(t, 2)
        if len(bh) < 2 or len(bl) < 2:
            return None
        if d == 1:
            ok = (bh[0][0] > bh[1][0] if need_hh else True) and bl[0][0] > bl[1][0] and C[t] > bl[0][0]
            return bh[0][1] if ok else None
        ok = (bl[0][0] < bl[1][0] if need_hh else True) and bh[0][0] < bh[1][0] and C[t] < bh[0][0]
        return bl[0][1] if ok else None

    TB = dow_machine(H, L, C, P['N_BIG'])[0] if S['g1'] == 'dowP' else None
    consumed = set()

    def setup(t, d, pattern):
        """足 t の確定時点で方向 d の注文案を作る（SPEC §5〜§9）。不成立なら理由コードを数えて None"""
        if np.isnan(atr[t]) or np.isnan(ma80[t]) or t < P['SLOPE_LB'] or np.isnan(ma80[t - P['SLOPE_LB']]):
            return rej('R00')
        if align is not None and align[t] != d:
            return rej('R01A')
        if pattern == 1:
            if S['g1'] == 'dow2':
                j_peak = g1_dow2(t, d, bb, S['require_hh'])
            else:
                j_peak = None
                if TB[t] == d:
                    sw_ = bb.highs(t, 1) if d == 1 else bb.lows(t, 1)
                    j_peak = sw_[0][1] if sw_ else None
            if j_peak is None:
                return rej('R01')
            ref_ma = ma80
        else:                                                  # パターン③（SPEC §11.3）
            if g1_dow2(t, d, bb, True) is not None:
                return rej('R01')                              # ①の局面
            j_peak = g1_dow2(t, d, bd, True)
            if j_peak is None:
                return rej('R01')
            bh, bl = bb.highs(t, 2), bb.lows(t, 2)
            if len(bh) < 2 or len(bl) < 2:
                return rej('R01')
            endsig = (bl[0][0] > bl[1][0] or C[t] > bh[0][0]) if d == 1 else (bh[0][0] < bh[1][0] or C[t] < bl[0][0])
            if not endsig:
                return rej('R01')
            if np.isnan(ma480[t]):
                return rej('R00')
            ref_ma = ma480
        a_t = atr[t]
        slope = (ma80[t] - ma80[t - P['SLOPE_LB']]) / a_t * d
        win = slice(j_peak + 1, t + 1)
        if d == 1:
            depth = float(np.nanmin((L[win] - ref_ma[win]) / atr[win]))
        else:
            depth = float(np.nanmin((ref_ma[win] - H[win]) / atr[win]))
        conv = float(np.nanmin(np.abs(ma20[win] - ma80[win]) / atr[win]))
        if S['place'] == 'touch':
            if S['g2'] and depth > P['ZONE_ATR']:
                return rej('R02')                              # G2: 押しが 4H MA に届いていない
        elif conv > P['CONV_ATR']:
            return rej('R02')
        # 1H 転換（SPEC §7.1。売りは鏡像）
        if d == 1:
            shl = bs.highs(t, 1)
            if not shl or shl[0][1] <= j_peak:
                return rej('R03')
            lvl, j_sh = shl[0]
            cands = [p for p, j in bs.lows(t, P['L0_SEARCH']) if j < j_sh]
            if not cands:
                return rej('R03')
            run_ext = float(np.min(L[j_sh + 1:t + 1]))
            if run_ext <= cands[0]:
                return rej('R04')                              # 安値切上げの崩れ
            if np.any(C[j_sh + 1:t + 1] > lvl):
                return rej('R05')                              # 消化済み
        else:
            sll = bs.lows(t, 1)
            if not sll or sll[0][1] <= j_peak:
                return rej('R03')
            lvl, j_sh = sll[0]
            cands = [p for p, j in bs.highs(t, P['L0_SEARCH']) if j < j_sh]
            if not cands:
                return rej('R03')
            run_ext = float(np.max(H[j_sh + 1:t + 1]))
            if run_ext >= cands[0]:
                return rej('R04')
            if np.any(C[j_sh + 1:t + 1] < lvl):
                return rej('R05')
        key = (d, int(j_sh))
        if S['one_fill'] and key in consumed:
            return rej('R06')
        if S['g3'] and (lvl - ref_ma[t]) * d / a_t > P['LVL_MAX_ATR']:
            return rej('R07')
        if S['slope_gate'] and pattern == 1 and slope < P['SLOPE_MIN']:
            return rej('R08')
        # 注文価格・損切り（SPEC §7.2）
        price = lvl + d * P['ENTRY_BUF_ATR'] * a_t
        buf = max(P['SL_BUF_ATR'] * a_t, P['SPREAD_FLOOR'] * s_nom) if S['sl_floor'] else P['SL_BUF_ATR'] * a_t
        lv = levels_at(t)
        tol_s = P['TOL_S'] * a_t
        anchor = run_ext
        if S['sl_mode'] == 'node':                             # 節目の外（kenjin_only・F+slnode）
            near = [x['price'] for x in lv if (x['touch'] >= 2 or x['d1']) and 0 <= (run_ext - x['price']) * d <= tol_s]
            if near:
                anchor = min(near) if d == 1 else max(near)
        sl = anchor - d * buf
        R = (price - sl) * d
        rel = int(TD[t] * d)
        rmax = P['R_MAX_ATR'] * (0.5 if (S['d1_gate'] == 'soft' and rel == -1) else 1.0)
        if S['rcap'] and R < P['R_MIN_ATR'] * a_t:
            return rej('R09')
        if S['rcap'] and R > rmax * a_t:
            return rej('R10')
        if R <= 0:
            return rej('R09')
        if S['d1_gate'] == 'strict' and rel == -1:
            return rej('R11')
        gap = (ma80[t] - ma480[t]) * d / a_t
        gap_prev = (ma80[t - 12] - ma480[t - 12]) * d / atr[t - 12] if t >= 12 else np.nan
        gap_bad = (not np.isnan(gap)) and (not np.isnan(gap_prev)) and gap > P['GAP_HI'] and gap > gap_prev
        if S['gap_gate'] and gap_bad:
            return rej('R12')
        if S['h1_transition'] and TS[t] == d:
            return rej('R13')
        # 背後の支え（SPEC §6.3。B = 押しの極値）
        pb = float(np.min(L[win])) if d == 1 else float(np.max(H[win]))
        types = set()
        for x in lv:
            if abs(x['price'] - pb) <= tol_s:
                if x['touch'] >= 2:
                    types.add('HZ')
                if (d == 1 and x['nh'] >= 1 and x['price'] < C[t]) or (d == -1 and x['nl'] >= 1 and x['price'] > C[t]):
                    types.add('FLIP')
        key_sw = [(p, j) for p, j in (bb.lows(t, 4) if d == 1 else bb.highs(t, 4)) if j < j_peak]
        if key_sw and abs(key_sw[0][0] - pb) <= tol_s:
            types.add('KEY')
        if S['support_gate'] and not types:
            return rej('R14')
        # 前方の反対勢力と目標（SPEC §6.4）
        tol_lv = P['TOL_LV'] * a_t
        th = float(np.max(H[j_peak:t + 1])) if d == 1 else float(np.min(L[j_peak:t + 1]))
        cf = []
        for x in lv:
            if (x['price'] - th) * d > tol_lv:
                if (S['cf_scope'] == 'strong' and x['touch'] >= P['CF_MIN_TOUCH']) or (S['cf_scope'] == 'daily' and x['d1']):
                    cf.append(x['price'])
        if not np.isnan(ma480[t]) and (ma480[t] - price) * d > 0:
            cf.append(float(ma480[t]))
        rr_cf = (min((c - price) * d for c in cf) / R) if cf else 99.0
        if S['clear_gate'] and rr_cf < P['RR_CF']:
            return rej('R15')
        tg = [th] + [x['price'] for x in lv if x['touch'] >= 2 or x['d1']]
        if not np.isnan(ma480[t]):
            tg.append(float(ma480[t]))
        tg = sorted([(x - price) * d for x in tg if (x - price) * d > 0])
        near_r = tg[0] / R if tg else 99.0
        if S['target_gate'] and near_r < S['target_gate']:
            return rej('R16')
        t1 = [v for v in tg if v / R >= P['TP1_MIN_R']]
        tp1 = price + d * (t1[0] if t1 else P['TP_DEFAULT_R'] * R)
        # スコア（SPEC §9。情報用）
        s1 = 20 if slope >= 0.10 else (10 if slope >= 0 else 0)
        s2 = 15 if depth <= 0 else 8
        s3 = 15 if len(types) >= 2 else (8 if len(types) == 1 else 0)
        s4 = 20 if rel == 1 else (10 if rel == 0 else 0)
        s5 = 15 if rr_cf >= 3 else (10 if rr_cf >= 2 else (5 if rr_cf >= 1 else 0))
        s6 = (8 if not gap_bad else 0) + (7 if conv <= P['CONV_ATR'] else 0)
        score = s1 + s2 + s3 + s4 + s5 + s6
        meta = dict(dir=d, pattern=pattern, score=score, rel=rel, rr_cf=round(min(rr_cf, 99.0), 2),
                    n_sup=len(types), r_atr=round(R / a_t, 2), year=idx[t].year,
                    s1=s1, s2=s2, s3=s3, s4=s4, s5=s5, s6=s6, sup='+'.join(sorted(types)),
                    slope=round(slope, 3), depth=round(depth, 3), gap=None if np.isnan(gap) else round(gap, 3),
                    conv=round(conv, 3), near_r=round(min(near_r, 99.0), 2), tp1=tp1)          # ログ・層別分析用（判定には使わない）
        return dict(dir=d, key=key, price=price, sl=sl, tp1=tp1, meta=meta)

    def open_market(m, t):
        """成行（次の足の始値）の約定。素朴ベースラインは約定価格から SL を決める"""
        sl = m['sl']
        if sl is None:
            sl = O[t] + m['dir'] * s_nom / 2 - m['dir'] * m['sl_dist']
        pos = br.open_position(idx[t], O[t], m['dir'], sl, tp1=m['tp1'] if S['partial'] else None,
                               tp1_frac=S['partial'], be_after_tp1=S['be'], meta=m['meta'])
        if pos is not None:
            pos.meta['entry_idx'] = t
            if m['key'] is not None:
                consumed.add(m['key'])
            br.process_bar(pos, idx[t], O[t], H[t], L[t], C[t])

    pend = None; market = None
    first = n
    for t in range(n):                                         # 判定開始（SPEC §2.7）
        if not np.isnan(atr[t]) and not np.isnan(ma80[t]) and t >= P['SLOPE_LB'] + 80:
            first = t; break
    if S['warmup'] is not None:
        first = S['warmup']
    for t in range(first, n):
        o, h, l, c = O[t], H[t], L[t], C[t]; tm = idx[t]
        # 1) 休場明け: 待機注文を取消し、建玉は始値で決済
        if gap_before[t] and S['calendar']:
            pend = None; market = None
            if S['weekend']:
                for pos in list(br.open):
                    br._close_part(pos, tm, br._exit_side(o, pos.direction), pos.remaining, 'GAP_FALLBACK')
        # 2) 注文の約定
        if market is not None and not br.open:
            m = market; market = None
            open_market(m, t)
        elif pend is not None and not br.open and S['entry'] == 'close':
            if (c - pend['price']) * pend['dir'] >= 0:         # F-stop: 終値が水準を越えたら次の足の始値で成行
                market = pend; pend = None
        elif pend is not None and not br.open:                 # 逆指値（SPEC §7.4）
            d, sp = pend['dir'], pend['price']
            touched = (h + s_nom / 2 >= sp) if d == 1 else (l - s_nom / 2 <= sp)
            if touched:
                o_side = o + d * s_nom / 2
                fill_mid = (max(o_side, sp) if d == 1 else min(o_side, sp)) - d * s_nom / 2
                pos = br.open_position(tm, fill_mid, d, pend['sl'], tp1=pend['tp1'] if S['partial'] else None,
                                       tp1_frac=S['partial'], be_after_tp1=S['be'], meta=pend['meta'])
                if pos is not None:
                    pos.meta['entry_idx'] = t; consumed.add(pend['key'])
                    br.process_bar(pos, tm, o, h, l, c, entry_bar=True)
                pend = None                                    # 届かなければ待機注文は残る（確定時に置き直す）
        # 3) 建玉の処理（窓開け → SL 優先 → 変種の TP1）
        for pos in list(br.open):
            if pos.entry_time != tm:
                br.process_bar(pos, tm, o, h, l, c)
        # 4) 確定時の管理: 週末・休場前の決済、構造トレール（SPEC §10.1）
        for pos in list(br.open):
            d = pos.direction
            if flat[t]:
                br.close(pos, tm + delta, c, 'WEEKEND'); continue
            if S['trail'] == 'none':
                continue
            book = bb if S['trail'] == 'big' else bs
            swl = book.lows(t, 1) if d == 1 else book.highs(t, 1)
            if swl and swl[0][1] > pos.meta['entry_idx'] - book.depth:
                bf = max(P['SL_BUF_ATR'] * atr[t], P['SPREAD_FLOOR'] * s_nom) if S['sl_floor'] else P['SL_BUF_ATR'] * atr[t]
                new_sl = swl[0][0] - d * bf
                if (new_sl - pos.sl) * d > 0 and (c - new_sl) * d > 0:
                    br.modify_sl(pos, new_sl)
        if flat[t]:
            pend = None; market = None
            continue
        if br.open or market is not None:
            continue
        if no_new[t] or rollover[t]:
            pend = None
            continue
        # 5) 新規の判定
        if S['entry'] == 'naive':                              # 素朴ベースライン（PREREGISTRATION §5）
            pend = None
            for d in (1, -1):
                if g1_dow2(t, d, bb, True) is not None:
                    if rng.random() < S['naive_p']:
                        market = dict(dir=d, sl=None, sl_dist=P['NAIVE_SL_ATR'] * atr[t], tp1=None, key=None,
                                      meta=dict(dir=d, pattern=0))
                    break
            continue
        best = None
        for d in (1, -1):
            s = setup(t, d, 1)
            if s is not None and (best is None or s['meta']['score'] > best['meta']['score']):
                best = s
        if best is None and S['p3']:
            for d in (1, -1):
                s = setup(t, d, 3)
                if s is not None and (best is None or s['meta']['score'] > best['meta']['score']):
                    best = s
        if best is None:
            pend = None                                        # INVALID: 待機注文を取消す
            continue
        if pend is None or pend['key'] != best['key']:
            funnel['ARMED'] = funnel.get('ARMED', 0) + 1
            best['left'] = S['expiry_emul']
            pend = best
        else:                                                  # 同じセットアップ: 価格・SL を置き直す
            if S['expiry_emul']:
                best['left'] = pend['left'] - 1
                if best['left'] <= 0:
                    pend = None
                    continue
            pend = best
    for pos in list(br.open):
        br.close(pos, idx[-1] + delta, C[-1], 'END')
    trades = [bk.trade_record(p, sym) for p in sorted(br.closed, key=lambda p: p.id)]
    return trades, funnel


def h1_g1_direction(h1, n_big=12, lookback=3000):
    """H1 足ごとの G1（4Hレベル dow2）の方向 +1/-1/0（その H1 足の確定時点）"""
    H, L, C = (h1[k].to_numpy(dtype=float) for k in ('High', 'Low', 'Close'))
    bb = ind.SwingBook(H, L, n_big, lookback=lookback)
    out = np.zeros(len(C), dtype=int)
    for t in range(len(C)):
        bh, bl = bb.highs(t, 2), bb.lows(t, 2)
        if len(bh) < 2 or len(bl) < 2:
            continue
        if bh[0][0] > bh[1][0] and bl[0][0] > bl[1][0] and C[t] > bl[0][0]:
            out[t] = 1
        elif bl[0][0] < bl[1][0] and bh[0][0] < bh[1][0] and C[t] < bh[0][0]:
            out[t] = -1
    return out


def run_p2(m15, h1, sym, sw=None):
    """パターン②（1H波 × M15転換。SPEC §11.1）を M15 足で実行。H1 版 G1 の方向との一致を必須にする。
    注意: 情報項目（節目・反対勢力・日足関係・スコア）は M15 上で代用計算している（既定ではゲートに使わない）。"""
    g = h1_g1_direction(h1)
    m = ind.closed_index_map(m15.index, pd.Timedelta(minutes=15), h1.index, pd.Timedelta(hours=1))
    align = np.where(m >= 0, g[np.clip(m, 0, None)], 0)
    return run_h1(m15, sym, sw, tf='M15', align=align)


def config(variant):
    """変種名 → スイッチ辞書（VARIANTS・SENSITIVITY・'naive:p=0.02:seed=3'）"""
    if variant in VARIANTS:
        return dict(VARIANTS[variant])
    if variant in SENSITIVITY:
        return dict(SENSITIVITY[variant])
    if variant.startswith('naive'):
        kv = dict(part.split('=') for part in variant.split(':')[1:])
        return dict(entry='naive', naive_p=float(kv.get('p', 0.02)), naive_seed=int(kv.get('seed', 0)))
    raise KeyError(variant)


def run(frames, sym, variant='fusion'):
    """evaluate.py から呼ぶ入口。frames: {'H1': df, 'M15': df（パターン②だけ）}。戻り値は取引の辞書リスト"""
    if variant == 'p2':
        return run_p2(frames['M15'], frames['H1'], sym)[0]
    return run_h1(frames['H1'], sym, config(variant))[0]
