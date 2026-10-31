"""監査テスト（先読みと約定モデル）:  python -m unittest discover -s fusion/tests -t .

test_strategy.TestCausality（合成データを2点で切り、決済済みの取引だけを比べる）が通らない経路を確かめる。
  - 休場日（CAL_CLOSED）・早仕舞い（CAL_EARLY）・休場前日・休場明けフォールバック（GAP_FALLBACK）
    建玉がある時点を一度回して見つけ、その時点に暦（calendar_sets をテスト中だけ差し替え）や
    データの空白を順に足していく。足した時点より前は変わらない（因果的）ので、経路を必ず通せる
  - F+p3・F+be・F+partial・oku_only（部分決済）・F-stop・kenjin_only・mincore_raw・素朴ベースライン・感度
  - M15 のパターン②（fs.run_p2 をそのまま通す。H1 足の区切りでない時刻でも切る）
比べるもの（足 c-1 まで）:
  - 各足の判定記録（trace の eval: 理由コード・途中の値・注文案）
  - 約定・決済（取引の全項目）と、各足の処理後の建玉の状態・SL の変更（Broker を記録用に差し替えて取る）
    足 c-1 の確定時のトレールのように、足 c 以降にしか効かない決定も比べられる
未来の作り方:
  - 切断（足 c 以降を捨てる）
  - 差し替え: 足 c 以降を足 c-1 の終値を軸に反転して値幅を 1.5 倍にし、足 c に大きなひげを付ける。
    反転だけだと TR（ATR）が変わらず、ひげがないと境界付近のスイングが崩れないことがあるため
  - 切る位置は、約定の1〜2本前・建玉中に BIG スイングが確定する足・直近の SMALL/BIG スイングが確定する足を含める
  （どれも、先読みを入れた変異体でテストが落ちることを確かめてある）
約定モデル（SPEC §7.4・§10.2）:
  - 逆指値は、約定足の直前の確定足で作った注文案（方向・価格・SL）で約定する。約定価格 = max(Ask 始値, price)
  - トレールの SL は、直前に処理した足の確定時点の帳簿・ATR・終値から決まり、次の足から効く
  - 約定足では SL だけを判定する。同じ足で SL と TP1 なら SL
  - F-stop の成行が新規停止・ロールオーバーをすり抜ける（SPEC §14 の擬似コードどおりだが §2.6 の表と食い違う。expectedFailure）
データ（fusion/data.py）:
  - UTC の1分足 → サーバー時間（NY+7）→ M15/H1/H4/D1。各足に、その区間より後の1分足が混ざらない（夏時間の切替・週末を含む）
実データ（FUSION_DATA_DIR の IS データ、2013〜2017）があれば、休場日の前後などで切った検査も行う。
"""
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from fusion import broker as bk
from fusion import data as fd
from fusion import indicators as ind
from fusion import strategy as fs

H1 = pd.Timedelta(hours=1)
M15 = pd.Timedelta(minutes=15)
LAST_AT_CLOSE = ('WEEKEND', 'END')            # 決済時刻が「足の確定時刻」になる決済理由


# ---------------------------------------------------------------- 道具
def synth(start, n, seed, freq='1h', vol=0.0009, regime=300):
    """トレンドと押し・戻りを繰り返す合成足（平日のみ。test_strategy.trending_h1 と同じ作り方）"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=int(n * 1.6), freq=freq)
    idx = idx[idx.dayofweek < 5][:n]
    drift = np.repeat(rng.choice([-1, 1], size=n // regime + 1) * vol * 0.13, regime)[:n]
    wave = vol * 0.67 * np.sin(np.arange(n) / 9.0)
    c = 1.2 + np.cumsum(drift + rng.normal(0, vol, n)) + wave
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, vol * 0.8, n)
    l = np.minimum(o, c) - rng.uniform(0, vol * 0.8, n)
    return pd.DataFrame({'Open': o, 'High': h, 'Low': l, 'Close': c, 'Volume': 1.0}, index=idx)


class RecBroker(bk.Broker):
    """各足の処理後の建玉の状態と、SL の変更（直前に処理した足の確定時）を記録する。判定には影響しない"""
    rec = []
    last_time = None

    def process_bar(self, pos, time, o, h, l, c, entry_bar=False):
        super().process_bar(pos, time, o, h, l, c, entry_bar)
        RecBroker.last_time = time
        RecBroker.rec.append((time, 'bar', pos.id, entry_bar, repr(pos.sl), repr(pos.remaining), repr(pos.exits)))

    def modify_sl(self, pos, new_sl):
        ok = super().modify_sl(pos, new_sl)
        RecBroker.rec.append((RecBroker.last_time, 'modify', pos.id, repr(new_sl), ok))
        return ok


class Run:
    """run_h1 / run_p2 を、判定記録（trace）と Broker の記録つきで回す"""

    def __init__(self, trades, ev, rec, align=None):
        self.trades, self.ev, self.rec, self.align = trades, ev, rec, align


def _traced_call(fn, *a, **k):
    ev, holder = {}, {}

    def tr(event, t, p):
        if event == 'eval':
            ev.setdefault(t, []).append(repr(p))
    orig_h1, orig_broker = fs.run_h1, fs.bk.Broker

    def run_h1_traced(*aa, **kk):
        kk['trace'] = tr
        holder['align'] = kk.get('align')
        return orig_h1(*aa, **kk)
    RecBroker.rec, RecBroker.last_time = [], None
    fs.run_h1, fs.bk.Broker = run_h1_traced, RecBroker
    try:
        trades = fn(*a, **k)[0]
    finally:
        fs.run_h1, fs.bk.Broker = orig_h1, orig_broker
    return Run(trades, ev, list(RecBroker.rec), holder.get('align'))


def traced(df, sym, sw=None):
    return _traced_call(lambda: fs.run_h1(df, sym, sw))


def traced_p2(m15, h1, sym):
    """fs.run_p2 をそのまま通す（H1 版 G1 の対応づけも本物）。run_p2 が run_h1 に渡す align も取り出す"""
    return _traced_call(lambda: fs.run_p2(m15, h1, sym))


def perturb_after(df, c, k=1.5):
    """足 c 以降を、足 c-1 の終値 p を軸に反転して p からの距離を k 倍にし、足 c に大きなひげ（高値 1.5p・安値 0.5p）を付ける"""
    p = float(df['Close'].iloc[c - 1])
    out = df.copy()
    o, h, l, cl = (df[x].to_numpy(dtype=float) for x in ('Open', 'High', 'Low', 'Close'))
    new = {'Open': p - k * (o - p), 'High': p - k * (l - p), 'Low': p - k * (h - p), 'Close': p - k * (cl - p)}
    new['High'][c] = max(new['High'][c], 1.5 * p)
    new['Low'][c] = min(new['Low'][c], 0.5 * p)
    for name, a in (('Open', o), ('High', h), ('Low', l), ('Close', cl)):
        v = a.copy()
        v[c:] = new[name][c:]
        out[name] = v
    return out


def exit_bar(tr, pos, delta):
    last = tr['exit_reason'].split('+')[-1]
    return pos[tr['exit_time'] - delta] if last in LAST_AT_CLOSE else pos[tr['exit_time']]


def entry_fields(tr):
    keys = ('entry_time', 'direction', 'entry', 'initial_sl', 'risk')
    return tuple(tr[k] for k in keys) + tuple(sorted((k, repr(v)) for k, v in tr.items() if k.startswith('m_')))


def boundary_cuts(df, run, rng, delta=H1, n_trades=2, n_big=12, n_small=3):
    """先読みが境界に現れやすい切断点: 約定の1〜2本前（待機注文あり）、建玉中に BIG スイングが確定する足、
    判定した足の次に SMALL/BIG のスイングが確定する足、それとランダムに1点"""
    H, L = df['High'].to_numpy(), df['Low'].to_numpy()
    ihb, ilb = ind.pivots(H, L, n_big)
    ihs, ils = ind.pivots(H, L, n_small)
    pos = {t: i for i, t in enumerate(df.index)}
    cuts = set()
    trades = run.trades
    for i in rng.permutation(len(trades))[:n_trades]:
        t = trades[int(i)]
        e, x = pos[t['entry_time']], exit_bar(t, pos, delta)
        cuts |= {e - 1, e - 2}
        piv = ilb if t['direction'] == 1 else ihb
        for b in range(e + 1, x + 1):
            if piv[b - n_big]:
                cuts.add(b)
                break
    evaluated = np.array(sorted(run.ev), dtype=int)
    for piv, depth in ((ihs, n_small), (ils, n_small), (ihb, n_big), (ilb, n_big)):
        cand = [int(t) + 1 for t in evaluated if t + 1 < len(df) and piv[t + 1 - depth]]
        if cand:
            cuts.add(int(rng.choice(cand)))
    cuts.add(int(rng.integers(len(df) // 3, len(df) - 2)))
    return sorted(c for c in cuts if 300 < c < len(df) - 1)


class CausalityMixin:
    def assert_same_past(self, full, part, idx, c, delta, label):
        """足 c-1 までの判定記録・建玉の記録・約定、足 c-1 までに終わった取引の全項目が同じ"""
        for t in range(c):
            if full.ev.get(t) != part.ev.get(t):
                self.fail(f'{label}: 足 {t}（{idx[t]}）の判定が変わった\n full={full.ev.get(t)}\n part={part.ev.get(t)}')
        last = idx[c - 1]
        ra = [r for r in full.rec if r[0] <= last]
        rb = [r for r in part.rec if r[0] <= last]
        if ra != rb:
            k = next((i for i, (a, b) in enumerate(zip(ra, rb)) if a != b), min(len(ra), len(rb)))
            self.fail(f'{label}: 建玉の記録が変わった（{k} 件目）\n full={ra[k:k + 2]}\n part={rb[k:k + 2]}')
        pos = {t: i for i, t in enumerate(idx)}
        fa = [t for t in full.trades if pos[t['entry_time']] < c]
        pa = [t for t in part.trades if pos[t['entry_time']] < c]
        self.assertEqual([entry_fields(t) for t in fa], [entry_fields(t) for t in pa], label)
        for a, b in zip(fa, pa):
            closed_a = exit_bar(a, pos, delta) < c and not a['exit_reason'].endswith('END')
            closed_b = exit_bar(b, pos, delta) < c and not b['exit_reason'].endswith('END')
            self.assertEqual(closed_a, closed_b, f'{label}: {a["entry_time"]}')
            if closed_a:
                self.assertEqual(repr(sorted(a.items())), repr(sorted(b.items())), f'{label}: {a["entry_time"]}')
            elif b['exit_reason'].endswith('END'):
                hist = b['exit_reason'].split('+')[:-1]           # 切断の終端までの部分決済の履歴
                self.assertEqual(a['exit_reason'].split('+')[:len(hist)], hist, f'{label}: {a["entry_time"]}')

    def check_cuts(self, df, sym, sw, cuts, label, modes=('perturb', 'cut')):
        full = traced(df, sym, sw)
        for c in cuts:
            for mode in modes:
                part = traced(df.iloc[:c], sym, sw) if mode == 'cut' else traced(perturb_after(df, c), sym, sw)
                self.assert_same_past(full, part, df.index, c, H1, f'{label} {mode} c={c}（{df.index[c - 1]}）')
        return full


# ---------------------------------------------------------------- 暦の経路を必ず通す合成データ
class PatchedCalendar:
    """fs.calendar_sets を差し替える（time_rules はモジュールの関数を呼ぶ）。追加の休場日・早仕舞い日を足す"""

    def __init__(self, extra_closed=(), extra_early=()):
        self.closed, self.early = set(extra_closed), set(extra_early)

    def __enter__(self):
        self.orig = fs.calendar_sets
        orig = self.orig

        def patched(sym, years):
            c, e = orig(sym, years)
            return c | self.closed, e | self.early
        fs.calendar_sets = patched
        return self

    def __exit__(self, *exc):
        fs.calendar_sets = self.orig


def _open_span(trades, a, b):
    """足の開始時刻 a〜b のあいだずっと建玉だった取引"""
    for t in trades:
        if t['entry_time'] < a and t['exit_time'] > b:
            return t
    return None


def build_calendar_scenario():
    """建玉中の足に、早仕舞い日・休場前日（翌平日を休場日にしてその日の足を1本だけ残す）・平日の12時間超の空白・
    待機注文がある足の後の空白・金曜の早い終了（決済足がない）を順に入れる。
    戻り値: (H1, 追加の休場日, 追加の早仕舞い日, 出来事の時刻の辞書)"""
    df = synth('2015-03-02', 4800, seed=11)
    closed, early, ev = set(), set(), {}
    real_closed, real_early = fs.calendar_sets('EURUSD', range(2015, 2017))

    def run():
        with PatchedCalendar(closed, early):
            return fs.run_h1(df, 'EURUSD')[0]

    def plain_day(dt):
        return dt.weekday() <= 3 and dt not in real_closed | real_early | closed | early and \
            fs.next_weekday(dt) not in real_closed | closed

    trades = run()
    days = sorted({ts.date() for ts in df.index})
    cursor = df.index[1500].date()
    # 1) 早仕舞い日: 16時〜20時足のあいだ建玉
    for dt in [d for d in days if d > cursor and plain_day(d)]:
        if _open_span(trades, pd.Timestamp(dt) + pd.Timedelta(hours=15), pd.Timestamp(dt) + pd.Timedelta(hours=20)):
            early.add(dt); ev['early'] = dt; cursor = dt + pd.Timedelta(days=3)
            break
    trades = run()
    # 2) 休場前日: 20時〜23時足のあいだ建玉。翌平日を休場日にし、その日は 00:00 の足だけ残す
    for dt in [d for d in days if d > cursor and plain_day(d)]:
        if _open_span(trades, pd.Timestamp(dt) + pd.Timedelta(hours=19), pd.Timestamp(dt) + pd.Timedelta(hours=23)):
            hol = fs.next_weekday(dt)
            closed.add(hol); ev['preholiday'] = dt; ev['closed'] = hol
            day = df.index.normalize() == pd.Timestamp(hol)
            df = df[~day | (df.index == pd.Timestamp(hol))]
            cursor = hol + pd.Timedelta(days=3)
            break
    trades = run()
    # 3) 平日の建玉中に14時間の空白（休場明けフォールバック）
    for t in trades:
        if t['entry_time'].date() > cursor and t['entry_time'].dayofweek <= 2 and 6 <= t['entry_time'].hour <= 12 \
                and t['exit_time'] - t['entry_time'] >= pd.Timedelta(hours=3):
            k = df.index.get_loc(t['entry_time']) + 1
            df = df.drop(df.index[k + 1:k + 15])
            ev['gap_with_position'] = df.index[k + 1]; cursor = df.index[k + 1].date() + pd.Timedelta(days=3)
            break
    # 4) 待機注文がある平日の足の後に13時間の空白を入れ、空白明けの足で価格に届かせる（約定せず取消されるべき）
    setups = {}

    def tr(event, t, p):
        if event == 'eval' and p['setup'] is not None:
            setups.setdefault(t, p['setup'])
    with PatchedCalendar(closed, early):
        fs.run_h1(df, 'EURUSD', trace=tr)
    for t, s in sorted(setups.items()):
        ts = df.index[t]
        if ts.date() > cursor and ts.dayofweek <= 3 and 3 <= ts.hour <= 16 and t + 20 < len(df):
            df = df.drop(df.index[t + 1:t + 14])
            k = t + 1                                          # 空白明けの足
            row = df.iloc[k].copy()
            if s['dir'] == 1:
                row['High'] = max(row['High'], s['price'] + 0.001)
            else:
                row['Low'] = min(row['Low'], s['price'] - 0.001)
            df.iloc[k] = row
            ev['gap_with_pending'] = df.index[k]; cursor = df.index[k].date() + pd.Timedelta(days=3)
            break
    trades = run()
    # 5) 金曜の建玉中にデータが 19 時で終わる（決済足 hc>=22 がない）→ 月曜の始値でフォールバック
    for t in trades:
        ft = t['exit_time']
        if t['entry_time'].date() > cursor and ft.dayofweek == 4 and ft.hour == 22 and t['exit_reason'] == 'WEEKEND' \
                and t['entry_time'] < ft.normalize() + pd.Timedelta(hours=18):
            fri = ft.normalize()
            df = df[~((df.index >= fri + pd.Timedelta(hours=19)) & (df.index < fri + pd.Timedelta(days=1)))]
            ev['friday_cut'] = fri
            break
    return df, closed, early, ev


class TestCalendarPathsCausality(CausalityMixin, unittest.TestCase):
    """休場日・早仕舞い・休場前日・休場明けフォールバックを通る合成データで、切断・差し替えしても過去が変わらない"""

    @classmethod
    def setUpClass(cls):
        cls.df, cls.closed, cls.early, cls.ev = build_calendar_scenario()

    def test_paths_are_exercised(self):
        df, ev = self.df, self.ev
        self.assertEqual(set(ev), {'early', 'preholiday', 'closed', 'gap_with_position', 'friday_cut', 'gap_with_pending'})
        with PatchedCalendar(self.closed, self.early):
            trades, _ = fs.run_h1(df, 'EURUSD')
            no_new, flat, roll, gap = fs.time_rules(df.index, 'EURUSD', dict(fs.DEFAULT_SW), H1, 12)
        ex = {(t['exit_reason'], t['exit_time']) for t in trades}
        e = pd.Timestamp(ev['early'])
        self.assertIn(('WEEKEND', e + pd.Timedelta(hours=19)), ex)                 # 早仕舞い日: hc>=19 の足の終値で決済
        p = pd.Timestamp(ev['preholiday'])
        self.assertIn(('WEEKEND', p + pd.Timedelta(hours=22)), ex)                 # 休場前日（金曜でない）: hc>=22
        self.assertIn(('GAP_FALLBACK', ev['gap_with_position']), ex)               # 平日の空白明けの始値
        mon = [t for t in trades if t['exit_reason'] == 'GAP_FALLBACK' and t['exit_time'] > ev['friday_cut']]
        self.assertTrue(mon and mon[0]['exit_time'].dayofweek == 0, mon[:1])       # 金曜の決済足がない → 月曜の始値
        g = df.index.get_loc(ev['gap_with_pending'])
        self.assertTrue(gap[g])
        self.assertFalse(any(t['entry_time'] == ev['gap_with_pending'] for t in trades))  # 空白明けは約定判定の前に取消
        c = df.index.get_loc(pd.Timestamp(ev['closed']))
        self.assertTrue(flat[c] and no_new[c])                                     # 休場日の足: 新規なし・全決済
        for t in [t for t in trades if t['exit_reason'] == 'GAP_FALLBACK']:        # 決済は空白明けの足の始値（Bid/Ask）
            o = df.loc[t['exit_time'], 'Open'] - t['direction'] * fs.S_NOM['EURUSD'] / 2
            self.assertAlmostEqual(t['entry'] + t['pnl_r'] * t['risk'] * t['direction'], o, places=9)

    def test_truncate_and_perturb_around_events(self):
        df, ev = self.df, self.ev
        idx = df.index
        pts = set()
        for key, hours in (('early', (16, 18, 19)), ('preholiday', (19, 21, 22))):
            for hh in hours:
                ts = pd.Timestamp(ev[key]) + pd.Timedelta(hours=hh)
                if ts in idx:
                    pts.add(idx.get_loc(ts))
        for key in ('gap_with_position', 'gap_with_pending'):
            k = idx.get_loc(ev[key])
            pts |= {k - 1, k, k + 1}
        k = idx.searchsorted(ev['friday_cut'] + pd.Timedelta(days=3))           # 月曜の最初の足
        pts |= {k - 1, k, k + 1}
        pts.add(idx.get_loc(pd.Timestamp(ev['closed'])) + 1)
        pts = sorted(p for p in pts if 200 < p < len(idx) - 1)
        with PatchedCalendar(self.closed, self.early):
            self.check_cuts(df, 'EURUSD', fs.config('fusion'), pts, 'fusion')
            for v in ('F+be', 'oku_only', 'F+p3'):
                self.check_cuts(df, 'EURUSD', fs.config(v), pts[::3], v, modes=('perturb',))
            for v in ('F-stop', 'kenjin_only', 'mincore_raw', 'F-calendar', 'naive:p=0.05:seed=1'):
                self.check_cuts(df, 'EURUSD', fs.config(v), pts[1::5], v, modes=('perturb',))


# ---------------------------------------------------------------- 合成データ: 変種と境界の切断点
class TestVariantsCausalitySynthetic(CausalityMixin, unittest.TestCase):
    """部分決済・建値移動・パターン③・感度・F-stop を含む変種で、判定記録と建玉の記録まで一致する"""

    def test_perturb_future_keeps_past(self):
        df = synth('2015-01-05', 4000, seed=5)
        rng = np.random.default_rng(7)
        for v in ('fusion', 'F+partial', 'F+be', 'oku_only', 'F+p3', 'F~dowP', 'F-stop', 'F+slnode', 'F+trail1h',
                  'S:N_BIG=16', 'mincore_raw'):
            sw = fs.config(v)
            full = traced(df, 'EURUSD', sw)
            n_big = sw.get('N_BIG', 12)
            for c in boundary_cuts(df, full, rng, n_big=n_big):
                part = traced(perturb_after(df, c), 'EURUSD', sw)
                self.assert_same_past(full, part, df.index, c, H1, f'{v} perturb c={c}（{df.index[c - 1]}）')

    def test_every_bar_cut_short_window(self):
        """短い区間では、全ての足で切って比べる（境界の取りこぼしがないこと）"""
        df = synth('2015-01-05', 1400, seed=21)
        full = traced(df, 'EURUSD', fs.config('F+be'))
        self.assertGreater(len(full.trades), 3)
        for c in range(1100, len(df) - 1, 7):
            part = traced(df.iloc[:c], 'EURUSD', fs.config('F+be'))
            self.assert_same_past(full, part, df.index, c, H1, f'F+be cut c={c}')


# ---------------------------------------------------------------- M15 のパターン②
def expected_align(m15, h1):
    """各 M15 足の確定時刻までに確定した最後の H1 足（確定時刻 = 開始 + 1h <= M15 の開始 + 15分）の G1 の向き。
    closed_index_map を使わずに数える"""
    g = fs.h1_g1_direction(h1)
    out = np.zeros(len(m15), dtype=int)
    h_close = list(h1.index + H1)
    j = -1
    for i, s in enumerate(m15.index):
        while j + 1 < len(h_close) and h_close[j + 1] <= s + M15:
            j += 1
        out[i] = g[j] if j >= 0 else 0
    return out


class TestPattern2Causality(CausalityMixin, unittest.TestCase):
    """パターン②（M15）: M15 と、それを再集計した H1 の両方の未来を差し替えても、過去の M15 判定は変わらない。
    切る時刻は H1 の区切り（xx:00）と区切りでない時刻（xx:30）の両方。xx:30 では、確定前の H1 足が変わる"""

    def check_p2(self, m15, sym, times):
        h1 = fd.resample(m15, 'H1')
        full = traced_p2(m15, h1, sym)
        self.assertGreater(len(full.trades), 2)
        np.testing.assert_array_equal(full.align, expected_align(m15, h1))     # 確定済みの H1 足だけを見る
        for T in times:
            c = int(m15.index.searchsorted(T))                 # 足 c-1 の確定時刻 = T
            self.assertEqual(m15.index[c - 1] + M15, T)
            for mode in ('perturb', 'cut'):
                mm = perturb_after(m15, c) if mode == 'perturb' else m15.iloc[:c]
                part = traced_p2(mm, fd.resample(mm, 'H1'), sym)
                self.assert_same_past(full, part, m15.index, c, M15, f'p2 {mode} T={T}')

    def test_synthetic_m15(self):
        m15 = synth('2015-02-02', 9000, seed=8, freq='15min', vol=0.00045, regime=1200)
        idx = m15.index
        times = []
        for frac in (0.45, 0.7, 0.9):
            b = idx[int(len(idx) * frac)].floor('h')
            times += [b + pd.Timedelta(minutes=30), b + pd.Timedelta(hours=3)]
        self.check_p2(m15, 'EURUSD', sorted(t for t in times if t in idx))

    def test_closed_index_map_m15_to_h1(self):
        m15 = synth('2015-02-02', 2000, seed=2, freq='15min', vol=0.00045)
        h1 = fd.resample(m15, 'H1')
        m = ind.closed_index_map(m15.index, M15, h1.index, H1)
        for i, t in enumerate(m15.index):
            close = t + M15
            if m[i] >= 0:
                self.assertLessEqual(h1.index[m[i]] + H1, close)
            if m[i] + 1 < len(h1):
                self.assertGreater(h1.index[m[i] + 1] + H1, close)
        # 10:45 の M15 足（11:00 確定）で 10:00 の H1 足が確定済み。10:30 の M15 足ではまだ 09:00 の H1 足
        t = m15.index[m15.index.searchsorted(m15.index[500].normalize() + pd.Timedelta(hours=10, minutes=45))]
        self.assertEqual(h1.index[m[m15.index.get_loc(t)]], t.floor('h'))
        self.assertEqual(h1.index[m[m15.index.get_loc(t) - 1]], t.floor('h') - H1)


# ---------------------------------------------------------------- 指標・帳簿・状態機械・時刻ルールの単体
class TestIndicatorCausality(unittest.TestCase):
    def test_swing_recognition_time(self):
        """足 t で帳簿が返すスイングは、足 t までのデータだけで判定できるもの（j <= t-N）に限る（SPEC §2.3）。
        足 t+1 の値が要るスイング（j = t-N+1）が直後にある足を選んで、足 t までで作った帳簿と比べる"""
        df = synth('2015-01-05', 2500, seed=4)
        H, L = df['High'].to_numpy(), df['Low'].to_numpy()
        for depth, lb in ((3, 400), (12, 3000), (72, 8000)):
            book = ind.SwingBook(H, L, depth, lb)
            ih, il = ind.pivots(H, L, depth)
            ts = [j + depth - 1 for j in np.flatnonzero(ih | il) if 2 * depth + 10 < j + depth - 1 < len(H) - 1][:40]
            self.assertTrue(ts)
            for t in ts:
                part = ind.SwingBook(H[:t + 1], L[:t + 1], depth, lb)
                self.assertEqual(book.highs(t, 8), part.highs(t, 8), (depth, t))
                self.assertEqual(book.lows(t, 8), part.lows(t, 8), (depth, t))
                self.assertTrue(all(j <= t - depth for _, j in book.highs(t, 8) + book.lows(t, 8)))

    def test_indicators_books_and_state_machines(self):
        df = synth('2015-01-05', 3000, seed=4)
        H, L, C = (df[k].to_numpy() for k in ('High', 'Low', 'Close'))
        ih3, _ = ind.pivots(H, L, 3)
        rng = np.random.default_rng(3)
        cuts = sorted({int(x) for x in rng.integers(200, 2990, size=4)} |
                      {int(j) + 3 for j in rng.choice(np.flatnonzero(ih3[200:2900]) + 200, size=3)})
        for c in cuts:
            mm = perturb_after(df, c)
            H2, L2, C2 = (mm[k].to_numpy() for k in ('High', 'Low', 'Close'))
            np.testing.assert_array_equal(ind.atr(H, L, C, 14)[:c], ind.atr(H2, L2, C2, 14)[:c])
            for n in (20, 80, 480):
                np.testing.assert_array_equal(ind.sma(C, n)[:c], ind.sma(C2, n)[:c])
            for depth in (3, 12, 72):
                a, b = ind.SwingBook(H, L, depth, 400), ind.SwingBook(H2, L2, depth, 400)
                for t in range(max(c - 30, 0), c):
                    self.assertEqual(a.highs(t, 6), b.highs(t, 6))
                    self.assertEqual(a.lows(t, 6), b.lows(t, 6))
                T1, E1 = fs.dow_machine(H, L, C, depth)
                T2, E2 = fs.dow_machine(H2, L2, C2, depth)
                np.testing.assert_array_equal(T1[:c], T2[:c])
                np.testing.assert_array_equal(E1[:c], E2[:c])
                T3, E3 = fs.dow_machine(H[:c], L[:c], C[:c], depth)
                np.testing.assert_array_equal(T1[:c], T3)
                np.testing.assert_array_equal(E1[:c], E3)
            np.testing.assert_array_equal(fs.h1_g1_direction(df)[:c], fs.h1_g1_direction(mm)[:c])

    def test_time_rules_do_not_depend_on_later_bars(self):
        idx = pd.date_range('2014-12-15', '2016-01-10', freq='1h')
        idx = idx[idx.dayofweek < 5]
        for sym in ('EURUSD', 'XAUUSD'):
            full = fs.time_rules(idx, sym, dict(fs.DEFAULT_SW), H1, 12)
            # 金曜 23時で終わる切断（次の足は月曜＝空白の直前）も含める
            for cut in ('2014-12-31 12:00', '2015-01-05 00:00', '2015-04-02 20:00', '2015-12-31 23:00'):
                k = idx.searchsorted(pd.Timestamp(cut))
                part = fs.time_rules(idx[:k], sym, dict(fs.DEFAULT_SW), H1, 12)
                for a, b in zip(full, part):
                    np.testing.assert_array_equal(a[:k], b)
        # データが年末で終わっても、早仕舞い（12/31 hc>=19）の判定は同じ
        part = idx[idx < '2015-01-01']
        no_new, flat, _, _ = fs.time_rules(part, 'EURUSD', dict(fs.DEFAULT_SW), H1, 12)
        self.assertTrue(flat[part.get_loc(pd.Timestamp('2014-12-31 18:00'))])
        self.assertFalse(flat[part.get_loc(pd.Timestamp('2014-12-31 17:00'))])


# ---------------------------------------------------------------- 約定モデル
class SpyBroker(bk.Broker):
    """呼び出しの順序を記録する（判定には影響しない）"""
    log = []

    def process_bar(self, pos, time, o, h, l, c, entry_bar=False):
        SpyBroker.log.append(('bar', time, pos.id, pos.direction, entry_bar, pos.sl, pos.tp1, pos.tp1_done,
                              (o, h, l, c), len(pos.exits)))
        super().process_bar(pos, time, o, h, l, c, entry_bar)
        SpyBroker.log.append(('after', time, pos.id, list(pos.exits)))

    def modify_sl(self, pos, new_sl):
        SpyBroker.log.append(('modify', pos.id, pos.sl, new_sl))
        return super().modify_sl(pos, new_sl)


def run_spy(df, sym, sw):
    ev = {}

    def tr(event, t, p):
        if event == 'eval':
            ev.setdefault(t, []).append(p)
    SpyBroker.log = []
    orig = fs.bk.Broker
    fs.bk.Broker = SpyBroker
    try:
        trades, _ = fs.run_h1(df, sym, sw, trace=tr)
    finally:
        fs.bk.Broker = orig
    return trades, ev, list(SpyBroker.log)


class TestExecutionModel(unittest.TestCase):
    def check_fills(self, df, sym, variant):
        """逆指値の約定は、直前の確定足の注文案どおり（SPEC §2.2・§7.4）。トレールの SL は、直前に処理した足の
        確定時点の帳簿・ATR・終値から決まり（SPEC §10.1）、次の足から効く"""
        sw = fs.config(variant)
        trades, ev, log = run_spy(df, sym, sw)
        pos = {t: i for i, t in enumerate(df.index)}
        O, Hh, Ll, Cc = (df[k].to_numpy() for k in ('Open', 'High', 'Low', 'Close'))
        s = fs.S_NOM[sym]
        trail = dict(fs.DEFAULT_SW, **sw)['trail']
        book = ind.SwingBook(Hh, Ll, fs.CORE['N_BIG'] if trail == 'big' else fs.CORE['N_SMALL'],
                             lookback=fs.FIX['LB_BIG'] if trail == 'big' else fs.FIX['LB_SMALL'])
        atr = ind.atr(Hh, Ll, Cc, 14)
        self.assertGreater(len(trades), 5)
        for t in trades:
            e, d = pos[t['entry_time']], t['direction']
            cands = [p['setup'] for p in ev.get(e - 1, []) if p['setup'] is not None]
            self.assertTrue(cands, f'{variant} {t["entry_time"]}: 直前の足に注文案がない')
            best = cands[0]
            for sp in cands[1:]:
                if sp['meta']['score'] > best['meta']['score']:
                    best = sp
            self.assertEqual(best['dir'], d)
            self.assertEqual(best['sl'], t['initial_sl'])
            exp = max(O[e] + s / 2, best['price']) if d == 1 else min(O[e] - s / 2, best['price'])
            self.assertAlmostEqual(t['entry'], exp, places=12)
            self.assertTrue((Hh[e] + s / 2 >= best['price']) if d == 1 else (Ll[e] - s / 2 <= best['price']))
        # 呼び出し順: 足 t の process_bar → 足 t の確定時の modify。足 t+1 は足 t で置いた SL で判定する
        next_sl = {}
        cur = None
        for rec in log:
            if rec[0] == 'bar':
                _, time, pid, d, entry_bar, sl, tp1, tp1_done, ohlc, nex = rec
                if pid in next_sl:
                    self.assertEqual(sl, next_sl.pop(pid))
                cur = rec
            elif rec[0] == 'after':
                new = rec[3][cur[9]:]
                if cur[4]:                                                    # 約定足: SL 以外の決済はない
                    self.assertTrue(all(x[3] in ('SL', 'TRAIL') for x in new), new)
                o, h, l, c = cur[8]
                d, sl, tp1, tp1_done = cur[3], cur[5], cur[6], cur[7]
                adv = (l - s / 2) if d == 1 else (h + s / 2)
                fav = (h - s / 2) if d == 1 else (l + s / 2)
                o_x = o - d * s / 2
                if (not cur[4] and tp1 is not None and not tp1_done and (o_x - tp1) * d < 0
                        and (adv - sl) * d <= 0 and (fav - tp1) * d >= 0):
                    self.assertNotEqual(new[0][3], 'TP1')                     # 同じ足で SL と TP1 → SL を優先
            elif rec[0] == 'modify':
                _, pid, old, new_sl = rec
                self.assertEqual(cur[2], pid)                                 # 直前に処理したのと同じ建玉の確定時
                t = pos[cur[1]]                                               # 直前に処理した足＝確定した足
                d = cur[3]
                sw_ = book.lows(t, 1) if d == 1 else book.highs(t, 1)
                exp = sw_[0][0] - d * max(fs.CORE['SL_BUF_ATR'] * atr[t], fs.FIX['SPREAD_FLOOR'] * s)
                self.assertEqual(new_sl, exp, f'{variant} {cur[1]}: トレールの SL が足 {t} の確定時点の値でない')
                self.assertGreater((Cc[t] - new_sl) * d, 0)
                next_sl[pid] = new_sl if (new_sl - old) * d > 0 else old

    def test_fills_and_trail_timing_synthetic(self):
        df = synth('2015-01-05', 5000, seed=3)
        for v in ('fusion', 'F+be', 'oku_only', 'F+p3', 'F+trail1h'):
            self.check_fills(df, 'EURUSD', v)

    def test_broker_entry_bar_and_same_bar_rules(self):
        # 約定足: 始値が SL の外でも、SL の価格で損切り（約定より前の値動きかもしれないので保守的に損切り扱い）
        b = bk.Broker(0.0)
        p = b.open_position('t0', 1.1000, 1, sl=1.0950, tp1=1.1050, tp1_frac=0.5)
        b.process_bar(p, 't0', 1.0940, 1.1080, 1.0930, 1.1060, entry_bar=True)
        self.assertEqual([x[3] for x in p.exits], ['SL'])
        self.assertAlmostEqual(p.exits[-1][1], 1.0950)
        self.assertAlmostEqual(p.realized_r, -1.0)
        # 約定足: 高値が TP1 を越えても TP1 はとらない
        b = bk.Broker(0.0)
        p = b.open_position('t0', 1.1000, 1, sl=1.0950, tp1=1.1050, tp1_frac=0.5)
        b.process_bar(p, 't0', 1.0990, 1.1080, 1.0960, 1.1060, entry_bar=True)
        self.assertEqual(p.exits, [])
        # 約定足でない足: SL と TP1 の両方 → SL（全量 −1R）。売りも同じ
        for d in (1, -1):
            b = bk.Broker(0.0002)
            p = b.open_position('t0', 1.1000, d, sl=1.1000 - d * 0.005, tp1=1.1000 + d * 0.005, tp1_frac=0.5)
            b.process_bar(p, 't1', 1.1000, 1.1060, 1.0940, 1.1000)
            self.assertEqual([x[3] for x in p.exits], ['SL'])
            self.assertAlmostEqual(p.realized_r, -1.0)
        # 始値が TP1 を越えた窓開け（建値移動あり）: TP1 は始値、残りはその足で建値に戻れば建値（理由は TRAIL と記録される）
        b = bk.Broker(0.0)
        p = b.open_position('t0', 1.1000, 1, sl=1.0950, tp1=1.1050, tp1_frac=0.5, be_after_tp1=True)
        b.process_bar(p, 't1', 1.1070, 1.1080, 1.0990, 1.1000)
        self.assertEqual([x[3] for x in p.exits], ['TP1', 'TRAIL'])
        self.assertAlmostEqual(p.realized_r, 0.5 * 0.0070 / 0.0050)

    @unittest.expectedFailure
    def test_fstop_market_order_respects_no_new_and_rollover(self):
        """既知の食い違い（監査所見）: F-stop では、新規停止（金曜 hc>=20・早仕舞い hc>=17）やロールオーバー（hc>=23）の
        足の終値で成行が決まり、次の足の始値で約定する。SPEC §2.6 の表（新規なし・23〜01時は注文が存在しない）に反する。
        原因は SPEC §14 の擬似コードと同じ順序（`if 建玉あり or market: continue` が no_new/rollover の取消より前）。
        IS 実データでは EURUSD 2015-07-03 19:00 足、EURJPY 2014-03-04 22:00 足など 7 件（F-stop 369 件中）。
        合成データで再現する: 21 時足の確定で置かれた待機注文に対して、22 時足（23 時確定＝ロールオーバー）の終値を越えさせる。
        直したら expectedFailure を外す"""
        df = synth('2015-01-05', 5000, seed=3)
        sw = fs.config('F-stop')
        ev = {}

        def tr(event, t, p):
            if event == 'eval' and p['setup'] is not None:
                ev[t] = p['setup']
        fs.run_h1(df, 'EURUSD', sw, trace=tr)
        t = next(t for t in sorted(ev) if df.index[t].hour == 21 and df.index[t].dayofweek <= 3 and t + 3 < len(df))
        s = ev[t]
        row = df.iloc[t + 1].copy()
        row['Close'] = s['price'] + s['dir'] * 0.0005
        row['High'], row['Low'] = max(row['High'], row['Close']), min(row['Low'], row['Close'])
        df.iloc[t + 1] = row
        trades, _ = fs.run_h1(df, 'EURUSD', sw)
        no_new, flat, roll, _ = fs.time_rules(df.index, 'EURUSD', dict(fs.DEFAULT_SW, **sw), H1, 12)
        pos = {x: i for i, x in enumerate(df.index)}
        self.assertTrue(any(x['entry_time'] == df.index[t + 2] for x in trades))   # 再現できていること
        bad = [x['entry_time'] for x in trades if no_new[pos[x['entry_time']] - 1] or roll[pos[x['entry_time']] - 1]]
        self.assertEqual(bad, [])


# ---------------------------------------------------------------- データ（再集計・サーバー時間）
class TestResampleNoFuture(unittest.TestCase):
    def test_m1_to_server_bars(self):
        """UTC の1分足（値＝通し番号で単調増加）→ サーバー時間の各足。夏時間の切替（2016-03-13, 2016-11-06）と週末を含む。
        各足の O/H/L/C は、その足の区間 [開始, 開始+Δ) の1分足だけから作られる（後の1分足が混ざると終値・高値が大きくなる）"""
        utc = pd.date_range('2016-03-09', '2016-03-16', freq='1min', inclusive='left').append(
            pd.date_range('2016-11-02', '2016-11-09', freq='1min', inclusive='left'))
        ny = utc.tz_localize('UTC').tz_convert('America/New_York')
        market_closed = ((ny.dayofweek == 4) & (ny.hour >= 17)) | (ny.dayofweek == 5) | ((ny.dayofweek == 6) & (ny.hour < 17))
        stray = (ny.dayofweek == 5) & (ny.hour == 12) & (ny.minute < 3)      # 休場中のわずかなティック（除かれるべき）
        utc = utc[~market_closed | stray]
        v = np.arange(len(utc), dtype=float)
        raw = pd.DataFrame({'time': utc, 'open': v, 'high': v + 0.25, 'low': v - 0.25, 'close': v + 0.1, 'volume': 1})
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'EUR_USD', '2016'))
            raw.to_csv(os.path.join(d, 'EUR_USD', '2016', 'm1.csv'), index=False)
            m1 = fd.load_oanda_m1('EUR_USD', d)
        self.assertTrue((m1.index.dayofweek < 5).all())
        self.assertEqual(len(m1), int((~market_closed).sum()))
        # サーバー時間 = NY + 7h（冬 UTC+2、夏 UTC+3）
        srv = fd.utc_to_server(pd.DatetimeIndex(['2016-03-11 21:59', '2016-03-14 00:00', '2016-11-04 20:59', '2016-11-07 00:00']))
        self.assertEqual(list(srv), [pd.Timestamp('2016-03-11 23:59'), pd.Timestamp('2016-03-14 03:00'),
                                     pd.Timestamp('2016-11-04 23:59'), pd.Timestamp('2016-11-07 02:00')])
        for tf in ('M15', 'H1', 'H4', 'D1'):
            r = fd.resample(m1, tf)
            self.assertTrue((r.index.dayofweek < 5).all(), tf)
            a = m1.index.searchsorted(r.index, side='left')
            b = m1.index.searchsorted(r.index + fd.TF_DELTA[tf], side='left')
            O, Hh, Ll, C = (m1[k].to_numpy() for k in ('Open', 'High', 'Low', 'Close'))
            for i in range(len(r)):
                self.assertGreater(b[i], a[i])
                self.assertEqual(r['Open'].iloc[i], O[a[i]], (tf, r.index[i]))
                self.assertEqual(r['Close'].iloc[i], C[b[i] - 1], (tf, r.index[i]))
                self.assertEqual(r['High'].iloc[i], Hh[a[i]:b[i]].max(), (tf, r.index[i]))
                self.assertEqual(r['Low'].iloc[i], Ll[a[i]:b[i]].min(), (tf, r.index[i]))
            self.assertEqual(int(b[-1] - a[0]), len(m1))                     # すべての1分足がどれか1本の足に入る
            if tf == 'H1':                                                     # 週末の境目: 金曜 23 時台まで、月曜 00 時台から
                self.assertEqual(r[r.index.dayofweek == 4].index.max().hour, 23)
                self.assertEqual(r[r.index.dayofweek == 0].index.min().hour, 0)

    def test_is_data_m15_resamples_to_h1(self):
        d = os.environ.get('FUSION_DATA_DIR')
        if not d or not os.path.exists(os.path.join(d, 'EURUSD_M15.csv')):
            self.skipTest('FUSION_DATA_DIR（EURUSD_M15.csv）がない')
        for sym in ('EURUSD', 'XAUUSD'):
            h1 = fd.load_prepared(sym, 'H1', d)
            m15 = fd.load_prepared(sym, 'M15', d)
            r = fd.resample(m15, 'H1')
            self.assertTrue(r.index.equals(h1.index), sym)
            np.testing.assert_array_equal(r[['Open', 'High', 'Low', 'Close']].to_numpy(),
                                          h1[['Open', 'High', 'Low', 'Close']].to_numpy())


# ---------------------------------------------------------------- 実データ（IS 2013〜2017）
class TestRealDataCausality(CausalityMixin, unittest.TestCase):
    """IS データを休場日の前後・早仕舞い日・Good Friday の前日などで切り、差し替え・切断しても過去が変わらない"""

    def load(self, sym, tf='H1', a='2015-03-01', b='2016-04-01'):
        d = os.environ.get('FUSION_DATA_DIR')
        if not d or not os.path.exists(os.path.join(d, f'{sym}_{tf}.csv')):
            self.skipTest(f'FUSION_DATA_DIR（{sym}_{tf}.csv）がない')
        df = fd.load_prepared(sym, tf, d)
        return df[(df.index >= a) & (df.index < b)]

    def cuts_at(self, df, stamps):
        return [k for k in (int(df.index.searchsorted(pd.Timestamp(s))) for s in stamps) if 300 < k < len(df) - 1]

    def test_fx_year_end_and_july3(self):
        df = self.load('EURUSD')
        cuts = self.cuts_at(df, ['2015-07-03 20:00', '2015-12-24 17:00', '2015-12-24 19:00', '2015-12-28 00:00',
                                 '2015-12-31 18:00', '2016-01-04 00:00'])
        self.check_cuts(df, 'EURUSD', fs.config('fusion'), cuts, 'fusion')
        for v in ('F+be', 'oku_only', 'F+p3'):
            self.check_cuts(df, 'EURUSD', fs.config(v), cuts[1::2], v, modes=('perturb',))

    def test_xau_good_friday_thanksgiving_july3(self):
        df = self.load('XAUUSD')
        cuts = self.cuts_at(df, ['2015-04-02 21:00', '2015-04-03 00:00', '2015-04-06 01:00', '2015-07-03 18:00',
                                 '2015-11-27 17:00', '2016-03-24 21:00', '2016-03-28 01:00'])
        self.check_cuts(df, 'XAUUSD', fs.config('fusion'), cuts, 'fusion')
        for v in ('F+be', 'kenjin_only'):
            self.check_cuts(df, 'XAUUSD', fs.config(v), cuts[::3], v, modes=('perturb',))

    def test_pattern2_real_m15(self):
        m15 = self.load('EURUSD', 'M15', '2015-09-01', '2016-02-15')
        times = [pd.Timestamp('2015-10-14 10:30'), pd.Timestamp('2015-12-24 18:00'), pd.Timestamp('2016-01-04 00:15'),
                 pd.Timestamp('2016-02-10 13:45')]
        TestPattern2Causality.check_p2(self, m15, 'EURUSD', [t for t in times if t in m15.index])

    def test_fills_match_previous_close_order(self):
        for sym in ('EURUSD', 'XAUUSD'):
            df = self.load(sym)
            for v in ('fusion', 'F+be'):
                TestExecutionModel.check_fills(self, df, sym, v)


if __name__ == '__main__':
    unittest.main()
