"""
FUSION-CORE v1.0 の最終評価（事前登録 fusion/PREREGISTRATION.md と SPEC §21 のとおりに1回だけ実行する）

  python -m fusion.final_eval --data-dir DIR --out OUTDIR [--workers 4] [--dry-run]

入力: DIR/<SYM>_H1.csv と DIR/<SYM>_M15.csv（fusion.data.prepare_oanda で作ったもの）。存在する銘柄だけ使う。
出力: OUTDIR/results.json   全数値
      OUTDIR/trades.csv.gz  全構成の全取引（config・pool・half・ref 列つき）
      OUTDIR/report.md      報告書の下書き（日本語。合否の結論が冒頭）

- 各銘柄の全期間を1本の系列として構成ごとに1回だけ走らせ、取引をエントリー時刻で評価プールに振り分ける
  （PREREGISTRATION §2〜§3。区間は「開始日0時」から「終了日の翌日0時」の直前まで）。
- 構成は §4 の全部を一度に走らせ、一度に出力する（一部だけを先に見ることはしない）。
- 乱数（素朴ベースラインの seed、ブートストラップの seed）と並び順を固定しているので、同じ入力からは同じ出力ができる。
- --dry-run: 開発データ（2013〜2017）の中に作った仮のプールで、コードの通り道だけを確かめる。結果の数値には意味がない。
  未接触データに触れないよう、読み込んだ足を 2013-01-01〜2017-12-31 に切り、開発期間の4銘柄（EURUSD・GBPUSD・EURJPY・
  XAUUSD）だけを使う。backtesting.py 同梱の EURUSD も 2018-01-01 より前に切る。
"""
import argparse
import gzip
import io
import json
import math
import multiprocessing as mp
import os
import platform
import resource
import subprocess
import time
from collections import OrderedDict
from statistics import NormalDist

import numpy as np
import pandas as pd

from fusion import data as fd
from fusion import evaluate as ev
from fusion import stats as st
from fusion import strategy as fs

ND = NormalDist()
NAN = float('nan')

# ---------------------------------------------------------------- 銘柄・構成（PREREGISTRATION §2・§4）
SYMBOLS = list(fs.SYMBOL_ORDER)                     # §2 の並び順（素朴ベースラインの銘柄番号 0〜6 もこの順）
FOUR = ['EURUSD', 'GBPUSD', 'EURJPY', 'XAUUSD']     # 開発期間の4銘柄
FX = [s for s in SYMBOLS if s != 'XAUUSD']
POOLS = ['U-A', 'U-B', 'U-C']
ABBR = {'EURUSD': 'EU', 'GBPUSD': 'GU', 'EURJPY': 'EJ', 'AUDUSD': 'AU', 'USDCAD': 'UC', 'AUDJPY': 'AJ', 'XAUUSD': 'XAU'}

MAIN = 'fusion'
COMPARE = ['oku_only', 'kenjin_only', 'mincore_final', 'ma_slope', 'fourp_score']    # 比較（§4）
COMPARE_JUDGED = ['oku_only', 'kenjin_only', 'mincore_final']                         # §8 の判定の対象
BASELINES = ['ma_slope', 'fourp_score']                                                # fusion/baselines.py（evaluate の登録を使う）
ABLATIONS = [k for k in fs.VARIANTS if k not in ('mincore_raw', MAIN) and k not in COMPARE]   # Holm の族（比較・感度を除く）
SENSITIVITY = list(fs.SENSITIVITY)                                                     # 報告のみ
SECONDARY = ['p2']                                                                     # パターン②（M15）。合否に使わない
NAIVE_P = [0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.08]                                 # §5 の格子
NAIVE_SEEDS = list(range(20))
V_SET = [k for k in fs.VARIANTS if k != 'mincore_raw'] + SENSITIVITY                  # DSR の V（§4 の fusion 系の全構成）

# ---------------------------------------------------------------- 統計の定数（PREREGISTRATION §6〜§9）
BOOT_REPS = 10000
SEED_MONTH = 12345          # §6 月ブロック・ブートストラップ
SEED_SYMYEAR = 2024         # §8 銘柄年ブートストラップ
DSR_N = 250
EULER_GAMMA = 0.5772156649
P1_T = 2.0
P2_MIN_N, P2_FRAC = 30, 0.60
P4_MARGIN = 0.10
P6_MIN = 0.90
NAIVE_TOL = 0.20
CMP_Z = 1.645
CMP_MEAN_FLOOR = -0.10
HOLM_ALPHA = 0.05
TEN_MONTH_MIN = 15

# SPEC §18 の照合表（4銘柄 2013〜2017、回数だけ）: 構成 → (4銘柄, EURUSD, GBPUSD, EURJPY, XAUUSD)
SPEC18 = OrderedDict([
    ('fusion', (531, 136, 124, 142, 129)), ('mincore_final', (537, 127, 122, 149, 139)),
    ('oku_only', (96, 17, 19, 34, 26)), ('kenjin_only', (136, 37, 33, 34, 32)),
    ('F-slope', (710, 178, 168, 181, 183)), ('F-G2', (1043, 269, 263, 260, 251)), ('F-HH', (960, 245, 219, 277, 219)),
    ('F-stop', (369, 90, 88, 102, 89)), ('F-trail', (529, 135, 124, 141, 129)), ('F-weekend', (493, 126, 119, 128, 120)),
    ('F-rcap', (579, 148, 140, 155, 136)), ('F-slfloor', (537, 136, 128, 143, 130)),
    ('F-onefill', (538, 137, 126, 143, 132)), ('F-rollover', (542, 139, 129, 144, 130)),
    ('F-calendar', (529, 134, 124, 142, 129)), ('F+G3', (361, 87, 79, 111, 84)), ('F+d1', (386, 93, 86, 113, 94)),
    ('F+d1soft', (423, 106, 94, 119, 104)), ('F+gap', (459, 115, 103, 124, 117)), ('F+clear', (357, 94, 79, 102, 82)),
    ('F+clear_d1', (364, 95, 81, 104, 84)), ('F+support', (462, 120, 110, 122, 110)),
    ('F+slnode', (485, 128, 111, 129, 117)), ('F+partial', (531, 136, 124, 142, 129)),
    ('F+be', (546, 142, 126, 145, 133)), ('F+trail1h', (551, 142, 130, 146, 133)), ('F+p3', (754, 201, 161, 199, 193)),
    ('F~dowP', (818, 195, 189, 236, 198)), ('F+h1trans', (358, 90, 87, 102, 79)), ('F~conv', (384, 88, 91, 103, 102)),
    ('p2', (599, 144, 137, 167, 151)),
])
SPEC18_TOL = 0.05
SPEC18_BT2017 = 18                  # fusion の BT 同梱ファイル 2017 年部分
SPEC18_TEN_MONTH = (23.7, 17, 33)   # fusion の EURUSD 10か月あたり（平均・最小・最大）

BASE_COLS = ['symbol', 'entry_time', 'exit_time', 'direction', 'entry', 'initial_sl', 'risk', 'pnl_r', 'exit_reason',
             'bars_held', 'mfe_r', 'mae_r']
STRATA = [('m_s1', 'S1 4H MA の向き'), ('m_s2', 'S2 押しの深さ'), ('m_s3', 'S3 背後の支え'), ('m_s4', 'S4 日足との関係'),
          ('m_s5', 'S5 前方の余白'), ('m_s6', 'S6 MA の状態'), ('m_rel', 'rel（日足との関係）'), ('m_n_sup', 'n_sup（背後の支えの種類数）')]


def naive_name(p, seed):
    return f'naive:p={p}:seed={seed}'


def all_configs(naive_p=NAIVE_P, naive_seeds=NAIVE_SEEDS):
    """§4 の全構成（固定の並び順）"""
    return [MAIN] + COMPARE + ABLATIONS + SENSITIVITY + SECONDARY + [naive_name(p, s) for p in naive_p for s in naive_seeds]


# ---------------------------------------------------------------- 評価プール（PREREGISTRATION §3）
def make_spec(dry_run=False):
    """本番は PREREGISTRATION §3 のプール。ドライランは開発データの中の仮のプール（数値は無意味）"""
    if not dry_run:
        return dict(
            dry_run=False,
            symbols=list(SYMBOLS),
            clip=None,
            bt_cut=None,                 # BT 同梱ファイルは全体（2018-02 まで）を数える（SPEC §21）
            pools=[('U-A', list(FX), '2005-04-01', '2008-12-31'),
                   ('U-A', ['XAUUSD'], '2006-07-01', '2008-12-31'),
                   ('U-B', list(SYMBOLS), '2018-01-01', '2020-05-14'),
                   ('U-C', ['AUDJPY'], '2009-01-01', '2017-12-31')],
            periods={'U-A': ('2005-04-01', '2008-12-31'), 'U-B': ('2018-01-01', '2020-05-14'),
                     'U-C': ('2009-01-01', '2017-12-31')},
            midpoints={'U-A': '2007-02-15 12:00', 'U-B': '2019-03-09 12:00', 'U-C': '2013-07-02 12:00'},
            refs=[('既知IS', list(FOUR), '2013-01-01', '2017-12-31'),
                  ('既知HO', list(FOUR), '2010-01-01', '2012-12-31'),
                  ('既知HO', ['AUDUSD', 'USDCAD'], '2013-01-01', '2017-12-31'),
                  ('既知HO-1', list(FOUR), '2010-01-01', '2012-12-31'),                 # SPEC §20 の内訳ごとの併記用
                  ('既知HO-2', ['AUDUSD', 'USDCAD'], '2013-01-01', '2017-12-31')],
            dsr_months=('2005-04', '2020-05'),
            dev=(list(FOUR), '2013-01-01', '2017-12-31'),
            cuts=['2009-01-01', '2018-01-01'],
        )
    return dict(
        dry_run=True,
        symbols=list(FOUR),
        clip=('2013-01-01', '2018-01-01'),                                    # 未接触データに触れないための切り取り
        bt_cut='2018-01-01',
        pools=[('U-A', ['EURUSD', 'GBPUSD', 'EURJPY'], '2013-04-01', '2014-12-31'),
               ('U-A', ['XAUUSD'], '2013-07-01', '2014-12-31'),               # 銘柄別の開始日の通り道
               ('U-B', list(FOUR), '2016-01-01', '2017-12-29'),
               ('U-C', ['EURJPY'], '2015-01-01', '2015-12-31')],
        periods={'U-A': ('2013-04-01', '2014-12-31'), 'U-B': ('2016-01-01', '2017-12-29'),
                 'U-C': ('2015-01-01', '2015-12-31')},
        midpoints=None,
        refs=[('既知IS', list(FOUR), '2013-01-01', '2017-12-31'),                       # 仮: 全期間
              ('既知HO', ['EURUSD', 'GBPUSD', 'XAUUSD'], '2015-01-01', '2015-12-31')],   # 仮: どのプールにも入らない2015年
        dsr_months=('2013-04', '2017-12'),
        dev=(list(FOUR), '2013-01-01', '2017-12-31'),
        cuts=['2016-01-01'],
    )


def day_range(a, b):
    """表の期間 a〜b（両端の日を含む）→ [a の0時, b の翌日0時)"""
    return pd.Timestamp(a), pd.Timestamp(b) + pd.Timedelta(days=1)


def midpoint(a, b):
    """「開始日0時」と「終了日の翌日0時」のちょうど中間（PREREGISTRATION §7 P3）"""
    lo, hi = day_range(a, b)
    return lo + (hi - lo) / 2


def pool_midpoints(spec):
    mids = OrderedDict((p, midpoint(*spec['periods'][p])) for p in POOLS if p in spec['periods'])
    for p, txt in (spec.get('midpoints') or {}).items():
        if mids[p] != pd.Timestamp(txt):
            raise ValueError(f'{p} の中点 {mids[p]} が事前登録の値 {txt} と一致しない')
    return mids


def ref_labels(spec):
    out = []
    for lab, _, _, _ in spec['refs']:
        if lab not in out:
            out.append(lab)
    return out


def combined_span(spec):
    """合算の期間 [最初のプールの開始, 最後のプールの終了の翌日)"""
    rng = [day_range(a, b) for _, _, a, b in spec['pools']]
    return min(r[0] for r in rng), max(r[1] for r in rng)


def assign(df, spec):
    """取引（symbol・entry_time 列）に pool・half・ref・year 列を付ける。どのプールにも入らない取引は pool=''"""
    out = df.copy()
    n = len(out)
    sym = out['symbol'].to_numpy(dtype=object)
    et = pd.DatetimeIndex(out['entry_time'])
    pool = np.full(n, '', dtype=object)
    for name, syms, a, b in spec['pools']:
        lo, hi = day_range(a, b)
        m = np.isin(sym, syms) & (et >= lo) & (et < hi)
        if np.any(m & (pool != '')):
            raise ValueError('評価プールが重なっている')
        pool[m] = name
    half = np.full(n, '', dtype=object)
    for name, mid in pool_midpoints(spec).items():
        m = pool == name
        half[m & (et < mid)] = '前半'
        half[m & (et >= mid)] = '後半'
    out['pool'] = pool
    out['half'] = half
    ref = np.full(n, '', dtype=object)
    for label in ref_labels(spec):
        m = np.zeros(n, dtype=bool)
        for lab, syms, a, b in spec['refs']:
            if lab == label:
                lo, hi = day_range(a, b)
                m |= np.isin(sym, syms) & (et >= lo) & (et < hi)
        out['_ref:' + label] = m
        ref = np.where(m, np.where(ref == '', label, ref + '|' + label), ref)
    out['ref'] = ref
    out['year'] = np.asarray(et.year, dtype=np.int64)
    return out


def chrono(df):
    """エントリー時刻順（同時刻は §2 の銘柄順、同じ実行の中は発生順）"""
    if len(df) == 0:
        return df
    return df.sort_values(['entry_time', 'sym_i', 'seq'], kind='mergesort')


# ---------------------------------------------------------------- 実行（各銘柄の全期間を構成ごとに1回だけ）
REG = ev.strategy_registry()
_CTX = {}


def _init(data_dir, clip):
    _CTX.clear()
    _CTX.update(data_dir=data_dir, clip=clip, cache={})


def _frame(sym, tf):
    if tf == 'H1' and sym in _CTX['cache']:
        return _CTX['cache'][sym]
    df = fd.load_prepared(sym, tf, _CTX['data_dir'])
    clip = _CTX['clip']
    if clip:
        df = df[(df.index >= clip[0]) & (df.index < clip[1])]
    if tf == 'H1':
        _CTX['cache'][sym] = df
    return df


def to_frame(trades, sym):
    df = pd.DataFrame(trades)
    if df.empty:
        df = pd.DataFrame({c: pd.Series(dtype=float) for c in BASE_COLS})
        df['entry_time'] = pd.Series(dtype='datetime64[ns]')
        df['exit_time'] = pd.Series(dtype='datetime64[ns]')
        df['exit_reason'] = pd.Series(dtype=object)
    df['symbol'] = sym
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    for c in ('entry', 'initial_sl', 'risk', 'pnl_r', 'mfe_r', 'mae_r'):
        df[c] = df[c].astype(float)
    df['direction'] = df['direction'].astype(np.int64)
    df['bars_held'] = df['bars_held'].astype(np.int64)
    df['seq'] = np.arange(len(df), dtype=np.int64)
    df['sym_i'] = SYMBOLS.index(sym) if sym in SYMBOLS else len(SYMBOLS)
    return df


def _job(job):
    """job = (銘柄, 構成, 切断日 or None)。戻り値 (job, 取引, 理由コード別件数, 足の情報, (経過秒, CPU秒))"""
    sym, cfg, cut = job
    t0, c0 = time.perf_counter(), time.process_time()
    h1 = _frame(sym, 'H1')
    if cut is not None:
        h1 = h1[h1.index < cut]
    info = dict(tf='H1', bars=len(h1), first=h1.index[0], last=h1.index[-1])
    funnel = {}
    if cfg == 'p2':
        m15 = _frame(sym, 'M15')
        info = dict(tf='M15', bars=len(m15), first=m15.index[0], last=m15.index[-1])
        trades, funnel = fs.run_p2(m15, h1, sym)
    elif cfg in BASELINES:
        trades = REG[cfg]({'H1': h1}, sym)
    else:
        trades, funnel = fs.run_h1(h1, sym, fs.config(cfg))
    return job, to_frame(trades, sym), dict(funnel), info, (time.perf_counter() - t0, time.process_time() - c0)


def build_jobs(syms, m15_syms, cfgs, cuts):
    """重い仕事から先に並べる（M15 → H1 の各構成 → 切断テスト → 素朴ベースライン）"""
    jobs = [(s, 'p2', None) for s in syms if 'p2' in cfgs and s in m15_syms]
    jobs += [(s, c, None) for s in syms for c in cfgs if c != 'p2' and not c.startswith('naive')]
    jobs += [(s, MAIN, cut) for s in syms for cut in cuts if MAIN in cfgs]
    jobs += [(s, c, None) for s in syms for c in cfgs if c.startswith('naive')]
    return jobs


def execute(jobs, data_dir, clip, workers, log):
    """仕事を並列に実行する。戻り値 ({job: (取引, 理由コード別件数, 足の情報)}, 仕事ごとの CPU 秒の合計)"""
    out = {}
    cpu = 0.0
    t0 = time.perf_counter()
    if workers <= 1:
        _init(data_dir, clip)
        it = map(_job, jobs)
        pool = None
    else:
        pool = mp.get_context('spawn').Pool(workers, initializer=_init, initargs=(data_dir, clip))
        it = pool.imap_unordered(_job, jobs, chunksize=1)
    try:
        for k, (job, df, funnel, info, (sec, csec)) in enumerate(it, 1):
            out[job] = (df, funnel, info)
            cpu += csec
            tag = f'{job[1]}' + (f'（{job[2]} で切断）' if job[2] else '')
            log(f'[{k:>4}/{len(jobs)}] {job[0]} {tag:<24} {len(df):>6}件 {sec:6.1f}秒（CPU {csec:5.1f}秒）'
                f'  経過 {time.perf_counter() - t0:7.0f}秒')
    except BaseException:
        if pool is not None:
            pool.terminate()                                   # 残りの仕事を待たずに止める
            pool.join()
        raise
    if pool is not None:
        pool.close()
        pool.join()
    return out, cpu


# ---------------------------------------------------------------- 統計（PREREGISTRATION §6）
def finite(x):
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def month_block_ci(df, reps=BOOT_REPS, seed=SEED_MONTH, q=(2.5, 97.5)):
    """月ブロック・ブートストラップ: 取引をエントリーの暦月でまとめ（銘柄は問わない）、取引のある月を月数と同じ個数だけ
    復元抽出して平均R（抽出した月の全取引の平均）を計算する。reps 回の q パーセンタイル（numpy の線形補間）"""
    if len(df) == 0:
        return dict(lo=NAN, hi=NAN, months=0, reps=reps, seed=seed)
    g = df.groupby(df['entry_time'].dt.to_period('M'))['pnl_r'].agg(['sum', 'count']).sort_index()
    s = g['sum'].to_numpy(float)
    c = g['count'].to_numpy(float)
    m = len(g)
    idx = np.random.default_rng(seed).integers(0, m, size=(reps, m))
    means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
    lo, hi = np.percentile(means, q)
    return dict(lo=float(lo), hi=float(hi), months=m, reps=reps, seed=seed)


def summary(df, boot=False):
    """§6 の成績（df はエントリー時刻順）。最大DD・最大連敗はエントリー時刻順に並べた累積R（fusion/stats.py）"""
    n = len(df)
    out = OrderedDict(trades=n)
    if n == 0:
        out.update(win_rate=NAN, total_r=0.0, avg_r=NAN, sd=NAN, se=NAN, t_stat=NAN, pf=NAN, max_dd_r=NAN,
                   max_losing_streak=0, avg_win_r=NAN, avg_loss_r=NAN, long=0, short=0)
    else:
        s = st.summarize(df)
        r = df['pnl_r'].to_numpy(float)
        sd = float(np.std(r, ddof=1)) if n > 1 else NAN
        out.update(win_rate=s['win_rate'], total_r=s['total_r'], avg_r=s['avg_r'], sd=sd,
                   se=sd / math.sqrt(n) if n > 1 else NAN, t_stat=s['t_stat'], pf=s['pf'], max_dd_r=s['max_dd_r'],
                   max_losing_streak=s['max_losing_streak'], avg_win_r=s['avg_win_r'], avg_loss_r=s['avg_loss_r'],
                   long=int((df['direction'] == 1).sum()), short=int((df['direction'] == -1).sum()))
    if boot:
        ci = month_block_ci(df)
        out.update(ci95_lo=ci['lo'], ci95_hi=ci['hi'], boot_months=ci['months'])
    return out


def by(df, key, order=None):
    """key 列の値ごとの成績（df はエントリー時刻順）"""
    out = OrderedDict()
    if len(df) == 0:
        return out
    vals = list(order) if order is not None else sorted(v for v in df[key].dropna().unique())
    for v in vals:
        lab = str(int(v)) if isinstance(v, (float, np.floating, int, np.integer)) and float(v).is_integer() else str(v)
        out[lab] = summary(df[df[key] == v])
    return out


def grade_of(score):
    """m_score → グレード（S ≥80、A 65〜79、B 50〜64、C <50）"""
    s = np.asarray(score, dtype=float)
    return np.where(np.isnan(s), '', np.where(s >= 80, 'S', np.where(s >= 65, 'A', np.where(s >= 50, 'B', 'C'))))


def drop_top(r, frac=0.01):
    """R の上位 ceil(0.01·n) 件を除いた残り（P5）"""
    r = np.sort(np.asarray(r, dtype=float))[::-1]
    k = (len(r) + 99) // 100 if frac == 0.01 else int(math.ceil(frac * len(r)))
    return k, r[k:]


def monthly_r(df, start, end):
    """月次R: その月にエントリーした全取引の pnl_r の合計。取引のない月は0（start〜end の各月）"""
    months = pd.period_range(start, end, freq='M')
    if len(df) == 0:
        return pd.Series(0.0, index=months)
    s = df.groupby(df['entry_time'].dt.to_period('M'))['pnl_r'].sum()
    outside = [str(m) for m in s.index if m not in set(months)]
    if outside:
        raise ValueError(f'月次Rの期間外の取引がある: {outside[:5]}')
    return s.reindex(months, fill_value=0.0).astype(float)


def sharpe(x):
    """SR = 平均 ÷ 標準偏差（不偏 ddof=1。年率化しない）"""
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return NAN
    sd = float(np.std(x, ddof=1))
    return float(np.mean(x)) / sd if sd > 0 else NAN


def moments(x):
    """歪度 γ₃ = m3/m2^1.5、尖度 γ₄ = m4/m2²（正規分布で3。m_k は平均からの k 次の標本モーメント）"""
    x = np.asarray(x, dtype=float)
    d = x - x.mean()
    m2, m3, m4 = np.mean(d ** 2), np.mean(d ** 3), np.mean(d ** 4)
    if not m2 > 0:
        return NAN, NAN
    return float(m3 / m2 ** 1.5), float(m4 / m2 ** 2)


def expected_max_sr(v, n=DSR_N):
    """SR₀ = √V × ((1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e)))"""
    if not finite(v) or v < 0:
        return NAN
    return math.sqrt(v) * ((1 - EULER_GAMMA) * ND.inv_cdf(1 - 1 / n) + EULER_GAMMA * ND.inv_cdf(1 - 1 / (n * math.e)))


def deflated_sharpe(sr, t, g3, g4, sr0):
    """DSR = Φ( (SR̂ − SR₀)·√(T−1) ÷ √(1 − γ₃·SR̂ + (γ₄−1)/4·SR̂²) )"""
    if not all(finite(v) for v in (sr, t, g3, g4, sr0)) or t < 2:
        return NAN
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2
    if den <= 0:
        return NAN
    return ND.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(den))


def dsr_block(monthly, trial_srs, n=DSR_N):
    x = np.asarray(monthly, dtype=float)
    srs = [v for v in trial_srs.values() if finite(v)]
    v = float(np.var(srs, ddof=1)) if len(srs) >= 2 else NAN
    sr = sharpe(x)
    g3, g4 = moments(x)
    sr0 = expected_max_sr(v, n)
    return OrderedDict(T=len(x), mean=float(x.mean()) if len(x) else NAN,
                       sd=float(np.std(x, ddof=1)) if len(x) > 1 else NAN, sr=sr, skew=g3, kurt=g4,
                       V=v, n_trials_for_V=len(srs), N=n, sr0=sr0, dsr=deflated_sharpe(sr, len(x), g3, g4, sr0))


def choose_naive_p(mean_counts, target, tol=NAIVE_TOL):
    """回数だけで p を選ぶ（PREREGISTRATION §5）: 20シードの合算取引数の平均が fusion の合算取引数に最も近い p
    （同じ近さなら小さい p）。±tol に入らなければ within_tol=False として報告する"""
    ps = sorted(mean_counts)
    best = min(ps, key=lambda p: (abs(mean_counts[p] - target), p))
    m = float(mean_counts[best])
    return OrderedDict(p=best, mean_count=m, target=int(target),
                       ratio=m / target if target > 0 else NAN,
                       within_tol=bool(target > 0 and abs(m - target) <= tol * target), tol=tol)


def holm(pvals, alpha=HOLM_ALPHA):
    """Holm のステップダウン法。pvals: {名前: p}（NaN は p=1 として扱う）。同じ p は渡した順"""
    names = list(pvals)
    pv = [float(pvals[k]) if finite(pvals[k]) else 1.0 for k in names]
    order = sorted(range(len(names)), key=lambda i: (pv[i], i))
    m = len(names)
    out, running, alive = OrderedDict(), 0.0, True
    for rank, i in enumerate(order):
        thr = alpha / (m - rank)
        running = max(running, min(1.0, (m - rank) * pv[i]))
        alive = alive and pv[i] <= thr
        out[names[i]] = OrderedDict(rank=rank + 1, p=pvals[names[i]], threshold=thr, p_holm=running, significant=alive)
    return OrderedDict((k, out[k]) for k in names)


def delta_test(f, v):
    """Δ平均R（変種 − fusion）、SE_Δ=√(SE_v²+SE_f²)、z=Δ/SE_Δ、両側 p（PREREGISTRATION §9）"""
    d = v['avg_r'] - f['avg_r']
    se = math.sqrt(v['se'] ** 2 + f['se'] ** 2) if finite(v['se']) and finite(f['se']) else NAN
    z = d / se if finite(d) and finite(se) and se > 0 else NAN
    p = 2 * ND.cdf(-abs(z)) if finite(z) else NAN
    return OrderedDict(delta=d, se_delta=se, z=z, p=p)


def sign_of(x):
    if not finite(x):
        return '·'
    return '+' if x > 0 else ('−' if x < 0 else '0')


def symbol_years(spec, syms, ranges):
    """プール内の「銘柄×暦年」の組（その年のプール区間に足があるもの）"""
    out = set()
    for name, ps, a, b in spec['pools']:
        lo, hi = day_range(a, b)
        for s in ps:
            if s not in syms or s not in ranges:
                continue
            first, last = ranges[s]
            for y in range(lo.year, (hi - pd.Timedelta(days=1)).year + 1):
                ylo, yhi = max(lo, pd.Timestamp(y, 1, 1)), min(hi, pd.Timestamp(y + 1, 1, 1))
                if first < yhi and last >= ylo:
                    out.add((name, s, y))
    return sorted(out, key=lambda k: (POOLS.index(k[0]), SYMBOLS.index(k[1]) if k[1] in SYMBOLS else 99, k[2]))


def symbol_year_totals(df, sy):
    idx = pd.MultiIndex.from_tuples(sy, names=['pool', 'symbol', 'year'])
    if len(df) == 0:
        return np.zeros(len(sy))
    s = df.groupby(['pool', 'symbol', 'year'])['pnl_r'].sum()
    s.index = pd.MultiIndex.from_tuples([(p, sy_, int(y)) for p, sy_, y in s.index], names=['pool', 'symbol', 'year'])
    known = set(sy)
    missing = [k for k in s.index if k not in known]
    if missing:
        raise ValueError(f'銘柄年の一覧にない取引がある: {missing[:5]}')
    return s.reindex(idx, fill_value=0.0).to_numpy(float)


def compare(f, v, sy, f_sum, v_sum, reps=BOOT_REPS, seed=SEED_SYMYEAR):
    """§8: 銘柄年ごとの総R差のブートストラップ90%区間と、平均R差 Δ ± 1.645·√(SE_f²+SE_v²)"""
    d = symbol_year_totals(f, sy) - symbol_year_totals(v, sy)
    k = len(d)
    if k:
        boot = d[np.random.default_rng(seed).integers(0, k, size=(reps, k))].mean(axis=1)
        lo, hi = (float(x) for x in np.percentile(boot, [5, 95]))
    else:
        lo = hi = NAN
    delta = f_sum['avg_r'] - v_sum['avg_r']
    se = math.sqrt(f_sum['se'] ** 2 + v_sum['se'] ** 2) if finite(f_sum['se']) and finite(v_sum['se']) else NAN
    mlo, mhi = delta - CMP_Z * se, delta + CMP_Z * se
    win = bool(finite(lo) and lo > 0 and finite(mlo) and mlo > CMP_MEAN_FLOOR)
    return OrderedDict(symbol_years=k, total_diff=float(d.sum()) if k else NAN,
                       per_symyear_diff=float(d.mean()) if k else NAN, per_symyear_ci90=[lo, hi],
                       total_diff_ci90=[lo * k, hi * k] if k else [NAN, NAN],
                       mean_diff=delta, se_diff=se, mean_diff_ci90=[mlo, mhi], fusion_wins=win)


def ten_month(df, segments):
    """連続10か月窓の回数（SPEC §18 の「10か月」列と同じ考え方）。segments: [(開始, 終了の翌日)]。
    区間に丸ごと入る暦月だけで窓を作り、つながった区間は1本にまとめる"""
    segs = []
    for lo, hi in sorted(segments):
        if segs and lo <= segs[-1][1]:
            segs[-1] = (segs[-1][0], max(hi, segs[-1][1]))
        else:
            segs.append((lo, hi))
    cnt = df.groupby(df['entry_time'].dt.to_period('M')).size() if len(df) else pd.Series(dtype=int)
    wins, months_used = [], 0
    for lo, hi in segs:
        months = [m for m in pd.period_range(lo, hi - pd.Timedelta(seconds=1), freq='M')
                  if m.start_time >= lo and (m + 1).start_time <= hi]
        c = [int(cnt.get(m, 0)) for m in months]
        months_used += len(months)
        wins += [sum(c[i:i + 10]) for i in range(len(c) - 9)]
    days = sum((hi - lo) / pd.Timedelta(days=1) for lo, hi in segs)
    return OrderedDict(mean=float(np.mean(wins)) if wins else NAN, min=int(min(wins)) if wins else None,
                       max=int(max(wins)) if wins else None, windows=len(wins), full_months=months_used,
                       trades=int(len(df)), per10m_simple=float(len(df) / days * 304.375) if days else NAN)


# ---------------------------------------------------------------- 合格基準（PREREGISTRATION §7）
def judge_p1(s):
    ok = s['trades'] > 1 and s['avg_r'] > 0 and s['t_stat'] >= P1_T and s['ci95_lo'] > 0
    return OrderedDict(ok=bool(ok), avg_r=s['avg_r'], t=s['t_stat'], ci95=[s['ci95_lo'], s['ci95_hi']])


def judge_p2(pool_avg, sym_stats):
    """pool_avg: {プール: 平均R}、sym_stats: {銘柄: (回数, 平均R)}（合算）"""
    pos_pools = [p for p, a in pool_avg.items() if finite(a) and a > 0]
    elig = [s for s, (n, a) in sym_stats.items() if n >= P2_MIN_N]
    pos_syms = [s for s in elig if finite(sym_stats[s][1]) and sym_stats[s][1] > 0]
    frac = len(pos_syms) / len(elig) if elig else NAN
    ok = len(pos_pools) >= 2 and bool(elig) and frac >= P2_FRAC
    return OrderedDict(ok=bool(ok), pools_positive=pos_pools, pools=list(pool_avg), eligible_symbols=elig,
                       positive_symbols=pos_syms, frac=frac)


def judge_p3(first, second):
    ok = finite(first) and finite(second) and first > 0 and second > 0
    return OrderedDict(ok=bool(ok), first_half_avg=first, second_half_avg=second)


def judge_p4(f_avg, seed_avgs):
    a = np.asarray([x for x in seed_avgs if finite(x)], dtype=float)
    if len(a) == 0 or len(a) != len(seed_avgs):
        return OrderedDict(ok=False, fusion_avg=f_avg, naive_mean=NAN, naive_p95=NAN, margin=P4_MARGIN,
                           note='素朴ベースラインの平均Rが計算できないシードがある')
    mean, p95 = float(a.mean()), float(np.percentile(a, 95))
    ok = finite(f_avg) and f_avg >= mean + P4_MARGIN and f_avg > p95
    return OrderedDict(ok=bool(ok), fusion_avg=f_avg, naive_mean=mean, naive_p95=p95, margin=P4_MARGIN,
                       need=mean + P4_MARGIN)


def judge_p5(r):
    k, rest = drop_top(r)
    avg = float(rest.mean()) if len(rest) else NAN
    return OrderedDict(ok=bool(finite(avg) and avg >= 0), n=int(len(r)), dropped=int(k), avg_r_after=avg,
                       total_r_after=float(rest.sum()) if len(rest) else NAN)


def judge_p6(dsr):
    return OrderedDict(ok=bool(finite(dsr) and dsr >= P6_MIN), dsr=dsr, threshold=P6_MIN)


def warn_long_short(long_avg, short_avg):
    fire = finite(long_avg) and finite(short_avg) and ((long_avg < 0) != (short_avg < 0))
    return OrderedDict(fire=bool(fire), long_avg=long_avg, short_avg=short_avg)


def warn_gap(fx_count, years):
    rate = fx_count / years if years > 0 else NAN
    return OrderedDict(fire=bool(finite(rate) and rate > 1.0), fx_count=int(fx_count), years=years, per_year=rate)


def warn_ten_month(mean10):
    return OrderedDict(fire=bool(finite(mean10) and mean10 < TEN_MONTH_MIN), mean=mean10, threshold=TEN_MONTH_MIN)


# ---------------------------------------------------------------- 集計
def config_block(d, syms, spec, strata=False):
    """1構成の成績（合算・プール別・前半後半・内訳・参考ウィンドウ）。d は assign 済み・時刻順"""
    comb = d[d['pool'] != '']
    pools = [p for p in POOLS if p in spec['periods']]
    blk = OrderedDict()
    blk['合算'] = summary(comb, boot=True)
    blk['プール別'] = OrderedDict((p, summary(comb[comb['pool'] == p], boot=True)) for p in pools)
    blk['前半後半'] = OrderedDict((h, summary(comb[comb['half'] == h])) for h in ('前半', '後半'))
    blk['プール別前半後半'] = OrderedDict((f'{p} {h}', summary(comb[(comb['pool'] == p) & (comb['half'] == h)]))
                                     for p in pools for h in ('前半', '後半'))
    blk['銘柄別'] = by(comb, 'symbol', [s for s in syms if (comb['symbol'] == s).any()])
    blk['売買別'] = OrderedDict((lab, summary(comb[comb['direction'] == v])) for lab, v in (('買い', 1), ('売り', -1)))
    blk['年別'] = by(comb, 'year')
    blk['決済理由別'] = by(comb, 'exit_reason')
    blk['上位1%除外'] = judge_p5(comb['pnl_r'].to_numpy(float))
    gap = comb['exit_reason'].astype(str).str.contains('GAP_FALLBACK', regex=False)
    blk['GAP_FALLBACK'] = OrderedDict(total=int(gap.sum()), fx=int((gap & comb['symbol'].isin(FX)).sum()),
                                      by_symbol=OrderedDict((s, int((gap & (comb['symbol'] == s)).sum())) for s in syms),
                                      fx_by_year=OrderedDict((str(int(y)), int(c)) for y, c in
                                                             comb[gap & comb['symbol'].isin(FX)].groupby('year').size().items()))
    blk['参考'] = OrderedDict((lab, summary(d[d['_ref:' + lab]], boot=True)) for lab in ref_labels(spec))
    blk['参考の銘柄別'] = OrderedDict((lab, by(d[d['_ref:' + lab]], 'symbol',
                                            [s for s in syms if (d[d['_ref:' + lab]]['symbol'] == s).any()]))
                                   for lab in ref_labels(spec))
    if strata and 'm_score' in comb:
        g = comb.assign(grade=grade_of(comb['m_score']))
        blk['グレード別'] = by(g, 'grade', [x for x in ('S', 'A', 'B', 'C') if (g['grade'] == x).any()])
        blk['層別'] = OrderedDict((k, by(comb, k)) for k, _ in STRATA if k in comb)
    return blk


def analyze(T, spec, syms, infos, cut_checks, bt, naive_p, naive_seeds, cfgs, meta):
    """T: {構成: assign 済みの全取引（時刻順）}。PREREGISTRATION §5〜§9 と SPEC §21 の全項目を計算する"""
    res = OrderedDict(meta=meta)
    pools = [p for p in POOLS if p in spec['periods']]
    present = [c for c in cfgs if not c.startswith('naive') and c in T]
    comb = OrderedDict((c, T[c][T[c]['pool'] != '']) for c in T)

    # 各構成の成績
    blocks = OrderedDict()
    for c in present:
        blocks[c] = config_block(T[c], syms, spec, strata=(c == MAIN))
    if 'p2' in blocks:                                         # SPEC §21: ②は U-A・U-B で副次的に評価する
        d = comb['p2']
        blocks['p2']['U-A＋U-B'] = summary(d[d['pool'].isin(['U-A', 'U-B'])], boot=True)
    res['configs'] = blocks
    f = blocks[MAIN]
    f_comb = comb[MAIN]

    # 素朴ベースライン（§5。p は回数だけで選ぶ。選ばなかった p は回数しか数えない）
    if naive_p and naive_seeds and all(naive_name(p, s) in comb for p in naive_p for s in naive_seeds):
        counts = OrderedDict((p, [int(len(comb[naive_name(p, s)])) for s in naive_seeds]) for p in naive_p)
        sel = choose_naive_p(OrderedDict((p, float(np.mean(v))) for p, v in counts.items()), len(f_comb))
        seeds = OrderedDict((s, summary(comb[naive_name(sel['p'], s)])) for s in naive_seeds)
        res['naive'] = OrderedDict(available=True, grid=naive_p, seeds=naive_seeds, counts=counts,
                                   mean_counts=OrderedDict((p, float(np.mean(v))) for p, v in counts.items()),
                                   selection=sel, chosen_seed_summaries=seeds,
                                   chosen_seed_avg_r=[seeds[s]['avg_r'] for s in naive_seeds])
    else:
        res['naive'] = OrderedDict(available=False, grid=naive_p, seeds=naive_seeds, chosen_seed_avg_r=[])

    # DSR（§6）: V は開発期間（4銘柄合算）の月次 SR の分散
    dev_syms, dev_a, dev_b = spec['dev']
    lo, hi = day_range(dev_a, dev_b)
    m0, m1 = pd.Period(dev_a, 'M'), pd.Period(dev_b, 'M')
    trial = OrderedDict()
    for c in V_SET:
        if c in T:
            d = T[c]
            dd = d[d['symbol'].isin(dev_syms) & (d['entry_time'] >= lo) & (d['entry_time'] < hi)]
            trial[c] = sharpe(monthly_r(dd, m0, m1).to_numpy())
    fm = monthly_r(f_comb, *spec['dsr_months'])
    res['dsr'] = dsr_block(fm.to_numpy(), trial)
    res['dsr']['months'] = list(spec['dsr_months'])
    res['dsr']['trial_sr'] = trial
    res['dsr']['monthly_r'] = OrderedDict((str(k), float(v)) for k, v in fm.items())

    # 合格基準（§7）
    sym_stats = OrderedDict((s, (v['trades'], v['avg_r'])) for s, v in f['銘柄別'].items())
    verdict = OrderedDict()
    verdict['P1'] = judge_p1(f['合算'])
    verdict['P2'] = judge_p2(OrderedDict((p, f['プール別'][p]['avg_r']) for p in pools), sym_stats)
    verdict['P3'] = judge_p3(f['前半後半']['前半']['avg_r'], f['前半後半']['後半']['avg_r'])
    verdict['P4'] = judge_p4(f['合算']['avg_r'], res['naive']['chosen_seed_avg_r'])
    verdict['P5'] = f['上位1%除外']
    verdict['P6'] = judge_p6(res['dsr']['dsr'])
    verdict['pass'] = all(verdict[k]['ok'] for k in ('P1', 'P2', 'P3', 'P4', 'P5', 'P6'))
    # 警告
    span_lo, span_hi = combined_span(spec)
    years = (span_hi - span_lo) / pd.Timedelta(days=365.25)
    eu_segs = [day_range(a, b) for _, ps, a, b in spec['pools'] if 'EURUSD' in ps]
    eu10 = ten_month(f_comb[f_comb['symbol'] == 'EURUSD'], eu_segs) if 'EURUSD' in syms else None
    verdict['warnings'] = OrderedDict(
        long_short=warn_long_short(f['売買別']['買い']['avg_r'], f['売買別']['売り']['avg_r']),
        gap_fallback=warn_gap(f['GAP_FALLBACK']['fx'], years),
        eurusd_10m=warn_ten_month(eu10['mean'] if eu10 else NAN))
    res['verdict'] = verdict

    # 比較（§8）
    sy = symbol_years(spec, syms, {s: (i['first'], i['last']) for s, i in infos.items()})
    cmp_ = OrderedDict()
    for c in COMPARE:
        if c in blocks:
            cmp_[c] = compare(f_comb, comb[c], sy, f['合算'], blocks[c]['合算'])
            cmp_[c]['judged'] = c in COMPARE_JUDGED
    res['comparisons'] = OrderedDict(symbol_years=[list(k) for k in sy], results=cmp_)

    # アブレーション（§9）と感度（報告のみ）
    def delta_rows(names):
        rows = OrderedDict()
        for c in names:
            if c not in blocks:
                continue
            r = delta_test(f['合算'], blocks[c]['合算'])
            r['trades'] = blocks[c]['合算']['trades']
            r['avg_r'] = blocks[c]['合算']['avg_r']
            r['pool_signs'] = OrderedDict((p, sign_of(blocks[c]['プール別'][p]['avg_r'] - f['プール別'][p]['avg_r']))
                                          for p in pools)
            r['symbol_signs'] = OrderedDict(
                (s, sign_of(blocks[c]['銘柄別'].get(s, {}).get('avg_r', NAN) - f['銘柄別'].get(s, {}).get('avg_r', NAN)))
                for s in syms)
            rows[c] = r
        return rows
    abl = delta_rows(ABLATIONS)
    hm = holm(OrderedDict((c, r['p']) for c, r in abl.items()))
    for c in abl:
        abl[c]['p_holm'] = hm[c]['p_holm']
        abl[c]['holm_rank'] = hm[c]['rank']
        abl[c]['significant'] = hm[c]['significant']
    res['ablations'] = OrderedDict(family_size=len(abl), alpha=HOLM_ALPHA, rows=abl)
    res['sensitivity'] = delta_rows(SENSITIVITY)

    # 副次
    res['secondary'] = OrderedDict(
        p2=OrderedDict(evaluated='p2' in blocks, note='SPEC §21 は U-A・U-B での副次評価（configs.p2 の「U-A＋U-B」）'),
        m15_downgrade=OrderedDict(evaluated=False, note='①-M15 降格は参照実装（fusion/strategy.py）に未実装のため評価しない（SPEC §11.2 の7）'))

    # 回数の確認
    checks = OrderedDict()
    checks['eurusd_10m_pools'] = eu10
    has_is = '既知IS' in ref_labels(spec)
    if 'EURUSD' in syms and has_is:
        ref_segs = [day_range(a, b) for lab, ps, a, b in spec['refs'] if lab == '既知IS' and 'EURUSD' in ps]
        d = T[MAIN]
        checks['eurusd_10m_known_is'] = ten_month(d[(d['symbol'] == 'EURUSD') & d['_ref:既知IS']], ref_segs)
        checks['eurusd_10m_known_is']['spec18'] = list(SPEC18_TEN_MONTH)
    checks['bt_bundled'] = bt
    rec = OrderedDict()
    for c, want in SPEC18.items():
        if c not in T or not has_is:
            continue
        d = T[c][T[c]['_ref:既知IS']]
        got = [int(len(d))] + [int((d['symbol'] == s).sum()) for s in FOUR]
        dev = [(g - w) / w if w else NAN for g, w in zip(got, want)]
        rec[c] = OrderedDict(spec18=list(want), got=got, rel_diff=dev,
                             within_5pct=bool(all(abs(x) <= SPEC18_TOL for x, s in zip(dev, ['ALL'] + FOUR)
                                                  if s == 'ALL' or s in syms)))
    checks['spec18_counts_known_is'] = rec
    checks['truncation'] = cut_checks
    res['checks'] = checks

    # fusion の理由コード別件数（全期間・銘柄別。プールには分けられない）
    res['funnel'] = meta.pop('_funnel', OrderedDict())
    return res


def truncation_checks(out, syms, cuts):
    """切断テスト: 途中で切った系列で走らせても、切った時点より前に決済した取引が完全に一致する（PREREGISTRATION §2）"""
    keys = ['entry_time', 'direction', 'entry', 'initial_sl', 'exit_time', 'pnl_r', 'exit_reason']
    rows = []
    for s in syms:
        full = out.get((s, MAIN, None))
        for cut in cuts:
            part = out.get((s, MAIN, cut))
            if full is None or part is None:
                continue
            last = part[2]['last']
            a = full[0][full[0]['exit_time'] < last][keys]
            b = part[0][part[0]['exit_time'] < last][keys]
            same = len(a) == len(b) and all(a[k].tolist() == b[k].tolist() for k in keys)
            rows.append(OrderedDict(symbol=s, cut=cut, last_bar=last, compared=int(len(a)), match=bool(same)))
    return OrderedDict(all_match=all(r['match'] for r in rows) if rows else None, rows=rows)


def bt_count(cut, log):
    """backtesting.py 同梱の EURUSD（2017-04〜2018-02）で fusion の回数だけを数える（SPEC §21）"""
    try:
        bt = fd.load_backtesting_eurusd()
    except FileNotFoundError as e:
        return OrderedDict(available=False, note=str(e))
    if cut is not None:
        bt = bt[bt.index < cut]                                # ドライランは 2018-01-01 より前だけ
    trades, _ = fs.run_h1(bt, 'EURUSD')
    n17 = sum(1 for t in trades if t['entry_time'] < pd.Timestamp('2018-01-01'))
    log(f'BT 同梱 EURUSD: {bt.index[0]}〜{bt.index[-1]} {len(bt)}本 → fusion {len(trades)}回（2017年分 {n17}回）')
    return OrderedDict(available=True, cut=cut, first=bt.index[0], last=bt.index[-1], bars=len(bt),
                       trades=len(trades), trades_2017=n17, spec18_bt2017=SPEC18_BT2017)


# ---------------------------------------------------------------- 出力
def clean(o):
    """JSON 用（NaN→null、±inf→文字列、numpy・Timestamp→素の型）"""
    if isinstance(o, dict):
        return OrderedDict((str(k), clean(v)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        x = float(o)
        if math.isnan(x):
            return None
        if math.isinf(x):
            return 'inf' if x > 0 else '-inf'
        return x
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if isinstance(o, pd.Period):
        return str(o)
    return o


def write_trades(path, T, cfgs):
    """全構成の全取引を1つの CSV（gzip、mtime=0 で毎回同じバイト列）に書く"""
    cols = ['config', 'pool', 'half', 'ref'] + BASE_COLS
    extra = []
    for c in cfgs:
        if c in T:
            extra += [k for k in T[c].columns if k.startswith('m_') and k not in extra]
    cols += extra
    with open(path, 'wb') as raw, gzip.GzipFile(filename='trades.csv', mode='wb', fileobj=raw, mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding='utf-8', newline='') as w:
            first = True
            for c in cfgs:
                if c not in T:
                    continue
                d = T[c].sort_values(['sym_i', 'seq'], kind='mergesort').assign(config=c).reindex(columns=cols)
                d.to_csv(w, index=False, header=first, date_format='%Y-%m-%d %H:%M:%S', lineterminator='\n')
                first = False


def git_state():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def git(*a):
        try:
            r = subprocess.run(['git', *a], cwd=root, capture_output=True, text=True, timeout=20)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    changed = git('diff', '--name-only', 'HEAD', '--', 'fusion')
    untracked = git('ls-files', '--others', '--exclude-standard', '--', 'fusion')
    return OrderedDict(commit=git('rev-parse', 'HEAD'),
                       modified_in_fusion=changed.split('\n') if changed else [],
                       untracked_in_fusion=untracked.split('\n') if untracked else [])


def run_all(data_dir, out_dir, workers=4, dry_run=False, log=print, spec=None, configs=None,
            naive_p=NAIVE_P, naive_seeds=NAIVE_SEEDS):
    """評価の本体。spec・configs・naive_p・naive_seeds の差し替えはテスト専用（CLI からは変えられない）"""
    t_start = time.perf_counter()
    spec = spec or make_spec(dry_run)
    cfgs = list(configs) if configs is not None else all_configs(naive_p, naive_seeds)
    if dry_run or spec['dry_run']:
        log('[final_eval] ドライラン：数値は無意味（開発データの中に作った仮のプールで、コードの通り道だけを確かめる）')
    pool_midpoints(spec)                                       # 中点が事前登録の値と合うことを先に確かめる
    syms = [s for s in spec['symbols'] if os.path.exists(os.path.join(data_dir, f'{s}_H1.csv'))]
    missing = [s for s in spec['symbols'] if s not in syms]
    m15_syms = [s for s in syms if os.path.exists(os.path.join(data_dir, f'{s}_M15.csv'))]
    if MAIN not in cfgs or not syms:
        raise SystemExit('fusion の構成か、H1 データのある銘柄がない')
    log(f'[final_eval] データ: {data_dir}  銘柄: {" ".join(syms)}（M15: {" ".join(m15_syms) or "なし"}）'
        + (f'  見つからない銘柄: {" ".join(missing)}' if missing else ''))
    jobs = build_jobs(syms, m15_syms, cfgs, spec['cuts'])
    log(f'[final_eval] 実行: {len(syms)}銘柄 × {len(cfgs)}構成（M15 のない銘柄の p2 を除く）＋切断テスト = {len(jobs)}件、{workers}並列')
    out, cpu = execute(jobs, data_dir, spec['clip'], workers, log)
    t_run = time.perf_counter() - t_start

    log('[final_eval] 集計中…')
    infos, m15_info = OrderedDict(), OrderedDict()
    for (s, c, cut), (_, _, info) in sorted(out.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or '')):
        if cut is None and info['tf'] == 'H1':
            infos.setdefault(s, info)
        if info['tf'] == 'M15':
            m15_info[s] = info
    infos = OrderedDict((s, infos[s]) for s in syms if s in infos)
    T = OrderedDict()
    for c in cfgs:
        parts = [out[(s, c, None)][0] for s in syms if (s, c, None) in out]
        if parts:
            T[c] = chrono(assign(pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0], spec))
    funnel = OrderedDict()
    for s in syms:
        if (s, MAIN, None) in out:
            funnel[s] = OrderedDict(sorted(out[(s, MAIN, None)][1].items()))
    meta = OrderedDict(
        title='FUSION-CORE v1.0 最終評価（PREREGISTRATION.md・SPEC §21）',
        dry_run=bool(spec['dry_run']),
        note=('ドライラン：数値は無意味。開発データ（2013〜2017）の中に作った仮のプールで、コードの通り道だけを確かめたもの'
              if spec['dry_run'] else '本番（未接触データでの1回だけの評価）'),
        git=git_state(), python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
        data_dir=os.path.abspath(data_dir), symbols=syms, missing_symbols=missing, m15_symbols=m15_syms,
        data=OrderedDict((s, OrderedDict(H1=infos.get(s), M15=m15_info.get(s))) for s in syms),
        clip=spec['clip'], pools=spec['pools'], periods=spec['periods'],
        midpoints=OrderedDict((p, m) for p, m in pool_midpoints(spec).items()),
        refs=spec['refs'], dsr_months=spec['dsr_months'], dev_window=spec['dev'], cuts=spec['cuts'],
        configs=[c for c in cfgs if not c.startswith('naive')], naive_grid=list(naive_p), naive_seeds=list(naive_seeds),
        prereg_naive=(list(naive_p) == NAIVE_P and list(naive_seeds) == NAIVE_SEEDS),
        seeds=OrderedDict(month_block=SEED_MONTH, symbol_year=SEED_SYMYEAR, reps=BOOT_REPS,
                          naive='numpy.random.default_rng(seed*1000+銘柄番号)'),
        _funnel=funnel)
    res = analyze(T, spec, syms, infos, truncation_checks(out, syms, spec['cuts']),
                  bt_count(spec['bt_cut'], log), list(naive_p), list(naive_seeds), cfgs, meta)

    os.makedirs(out_dir, exist_ok=True)
    js = clean(res)
    with open(os.path.join(out_dir, 'results.json'), 'w', encoding='utf-8') as fh:
        json.dump(js, fh, ensure_ascii=False, indent=1, allow_nan=False)
        fh.write('\n')
    write_trades(os.path.join(out_dir, 'trades.csv.gz'), T, cfgs)
    with open(os.path.join(out_dir, 'report.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_report(js))
    v = res['verdict']
    tag = '（ドライラン・数値は無意味）' if spec['dry_run'] else ''
    log(f'[final_eval] 判定{tag}: {"合格" if v["pass"] else "不合格"}  '
        + ' '.join(f'{k}={"○" if v[k]["ok"] else "×"}' for k in ('P1', 'P2', 'P3', 'P4', 'P5', 'P6')))
    log(f'[final_eval] 出力: {out_dir}/results.json, trades.csv.gz, report.md')
    log(f'[final_eval] 所要時間: 実行 {t_run:.0f}秒（仕事の CPU 時間の合計 {cpu:.0f}秒）、'
        f'合計 {time.perf_counter() - t_start:.0f}秒')
    log(f'[final_eval] ピークメモリ: 本体 {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}MB、'
        f'子プロセスの最大 {resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024:.0f}MB')
    return res


# ---------------------------------------------------------------- 報告書（report.md）
def _n(x, fmt='{:+.3f}', na='—'):
    if isinstance(x, str):
        return '∞' if x == 'inf' else x
    return fmt.format(x) if finite(x) else na


def _pct(x):
    return f'{x * 100:.1f}%' if finite(x) else '—'


def _pf(x):
    return '∞' if x == 'inf' else _n(x, '{:.2f}')


def _ci(lo, hi):
    return f'[{_n(lo)}, {_n(hi)}]' if finite(lo) or finite(hi) else '—'


def _ts(x, n=16):
    return str(x)[:n].replace('T', ' ') if x else '—'


def _table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|']
    out += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(out)


def _srow(name, s, ci=False):
    row = [name, s['trades'], _pct(s['win_rate']), _n(s['total_r'], '{:+.1f}'), _n(s['avg_r'])]
    if ci:
        row.append(_ci(s.get('ci95_lo'), s.get('ci95_hi')))
    row += [_n(s['t_stat'], '{:+.2f}'), _pf(s['pf']), _n(s['max_dd_r'], '{:+.1f}'), s['max_losing_streak'],
            f"{s['long']}/{s['short']}"]
    return row


def _sheads(ci=False):
    h = ['', '回数', '勝率', '総R', '平均R']
    if ci:
        h.append('95%区間（月ブロック）')
    return h + ['t', 'PF', '最大DD(R)', '最大連敗', '買い/売り']


def _short_rows(blk):
    return [[k, v['trades'], _pct(v['win_rate']), _n(v['total_r'], '{:+.1f}'), _n(v['avg_r']), _n(v['t_stat'], '{:+.2f}'),
             _pf(v['pf'])] for k, v in blk.items()]


SHORT_HEADS = ['', '回数', '勝率', '総R', '平均R', 't', 'PF']
OK = {True: '○', False: '×'}


def render_report(r):
    m, v, cf = r['meta'], r['verdict'], r['configs']
    f = cf[MAIN]
    pools = [p for p in POOLS if p in m['periods']]
    L = [('# 【ドライラン：数値は無意味】' if m['dry_run'] else '# ') + 'FUSION-CORE v1.0 最終評価 報告書（下書き）', '']
    if m['dry_run']:
        L += ['> **ドライラン：数値は無意味**。開発データ（2013〜2017、4銘柄）の中に作った仮のプールで、評価スクリプトの'
              '通り道だけを確かめたものです。合否・比較・アブレーション・DSR の数値は、優位性について何も言いません。', '']
    failed = [k for k in ('P1', 'P2', 'P3', 'P4', 'P5', 'P6') if not v[k]['ok']]
    w = v['warnings']
    L += ['## 結論', '',
          f"- **判定：{'合格' if v['pass'] else '不合格'}**"
          + ('（P1〜P6 をすべて満たした）' if v['pass'] else f"（満たさなかった基準：{'、'.join(failed)}）"),
          f"- 警告：買いと売りの片方だけがマイナス＝{'あり' if w['long_short']['fire'] else 'なし'}、"
          f"GAP_FALLBACK（FX）が年1件超＝{'あり' if w['gap_fallback']['fire'] else 'なし'}"
          f"（{w['gap_fallback']['fx_count']}件／{_n(w['gap_fallback']['years'], '{:.2f}')}年）、"
          f"EURUSD の10か月あたり回数が15回未満＝{'あり' if w['eurusd_10m']['fire'] else 'なし'}"
          f"（{_n(w['eurusd_10m']['mean'], '{:.1f}')}回）"]
    cmp_ = r['comparisons']['results']
    L.append('- 比較（§8）：' + '、'.join(f"{c} に対して「{'fusion の勝ち' if x['fusion_wins'] else '勝ちとは言えない'}」"
                                       for c, x in cmp_.items() if x['judged']))
    sig = [c for c, x in r['ablations']['rows'].items() if x['significant']]
    L.append(f"- アブレーション（§9、Holm 補正 {r['ablations']['family_size']}変種・α=0.05）：有意な変種＝"
             + ('、'.join(sig) if sig else 'なし'))
    g = m['git']
    L.append(f"- 実行したコミット：`{g['commit']}`" + ('（fusion/ に未コミットの変更あり：'
                                                 + '、'.join(g['modified_in_fusion'] + g['untracked_in_fusion']) + '）'
                                                 if g['modified_in_fusion'] or g['untracked_in_fusion'] else ''))
    L += ['', _table(['#', '基準', '値', '判定'], [
        ['P1', '合算の平均R＞0、t≥2.0、月ブロック95%区間の下限＞0',
         f"平均 {_n(v['P1']['avg_r'])}R、t={_n(v['P1']['t'], '{:+.2f}')}、区間 {_ci(*v['P1']['ci95'])}", OK[v['P1']['ok']]],
        ['P2', 'U-A・U-B・U-C のうち2つ以上で平均R＞0、かつ30回以上の銘柄の60%以上で平均R＞0',
         f"平均R＞0 のプール {len(v['P2']['pools_positive'])}/{len(v['P2']['pools'])}"
         f"（{'、'.join(v['P2']['pools_positive']) or 'なし'}）、銘柄 {len(v['P2']['positive_symbols'])}/"
         f"{len(v['P2']['eligible_symbols'])}（{_pct(v['P2']['frac'])}）", OK[v['P2']['ok']]],
        ['P3', '中点で分けた前半・後半の合算がどちらも平均R＞0',
         f"前半 {_n(v['P3']['first_half_avg'])}R、後半 {_n(v['P3']['second_half_avg'])}R", OK[v['P3']['ok']]],
        ['P4', '平均R ≥ 素朴20シードの平均＋0.10R、かつ95パーセンタイル超',
         f"fusion {_n(v['P4']['fusion_avg'])}R、素朴 平均 {_n(v['P4']['naive_mean'])}R・95%点 {_n(v['P4']['naive_p95'])}R",
         OK[v['P4']['ok']]],
        ['P5', 'R 上位1%（ceil(0.01·n) 件）を除いても平均R ≥ 0',
         f"{v['P5']['dropped']}件を除いて {_n(v['P5']['avg_r_after'])}R", OK[v['P5']['ok']]],
        ['P6', 'DSR ≥ 0.90', f"DSR={_n(v['P6']['dsr'], '{:.3f}')}", OK[v['P6']['ok']]],
    ]), '']

    # 1. 実行条件
    L += ['## 1. 実行条件', '',
          f"- データ：`{m['data_dir']}`（{m['note']}）",
          f"- Python {m['python']}、numpy {m['numpy']}、pandas {m['pandas']}",
          f"- 乱数：月ブロック seed={m['seeds']['month_block']}、銘柄年 seed={m['seeds']['symbol_year']}、"
          f"各 {m['seeds']['reps']:,}回。素朴ベースライン {m['seeds']['naive']}（seed {m['naive_seeds'][0]}〜{m['naive_seeds'][-1]}）"]
    if not m['prereg_naive']:
        L.append('- **注意：素朴ベースラインの格子・シードが事前登録と違う（テスト用の設定）**')
    if m['missing_symbols']:
        L.append(f"- 見つからなかった銘柄：{'、'.join(m['missing_symbols'])}")
    if m['clip']:
        L.append(f"- 読み込んだ足の切り取り：{m['clip'][0]} 以上 {m['clip'][1]} 未満（ドライラン）")
    L += ['', _table(['銘柄', 'H1 期間', 'H1 本数', 'M15 期間', 'M15 本数'], [
        [s, f"{_ts(d['H1']['first'])} 〜 {_ts(d['H1']['last'])}" if d['H1'] else '—', d['H1']['bars'] if d['H1'] else '—',
         f"{_ts(d['M15']['first'])} 〜 {_ts(d['M15']['last'])}" if d['M15'] else '—', d['M15']['bars'] if d['M15'] else '—']
        for s, d in m['data'].items()]), '']
    L += [_table(['プール', '銘柄', 'エントリー時刻の範囲（開始日0時以上、終了日の翌日0時未満）', '中点'], [
        [p, '、'.join(ps), f'{a} 〜 {b}', _ts(m['midpoints'].get(p))]
        for p, ps, a, b in m['pools']]), '']
    L += [_table(['参考ウィンドウ（合否に使わない）', '銘柄', '範囲'],
                 [[lab, '、'.join(ps), f'{a} 〜 {b}'] for lab, ps, a, b in m['refs']]), '']

    # 2. fusion の成績
    L += ['## 2. fusion の成績', '', '### 合算・プール別', '',
          _table(_sheads(True), [_srow('合算', f['合算'], True)] + [_srow(p, f['プール別'][p], True) for p in pools]), '',
          '### 前半・後半（P3）', '',
          _table(SHORT_HEADS, _short_rows(f['前半後半']) + _short_rows(f['プール別前半後半'])), '',
          '### 銘柄別', '', _table(SHORT_HEADS, _short_rows(f['銘柄別'])), '',
          '### 売買別', '', _table(SHORT_HEADS, _short_rows(f['売買別'])), '',
          '### 年別（エントリーの暦年）', '', _table(SHORT_HEADS, _short_rows(f['年別'])), '',
          '### 決済理由別', '', _table(SHORT_HEADS, _short_rows(f['決済理由別'])), '',
          '### グレード別（m_score：S≥80、A 65〜79、B 50〜64、C<50）', '', _table(SHORT_HEADS, _short_rows(f.get('グレード別', {}))), '']
    for key, lab in STRATA:
        if key in f.get('層別', {}):
            L += [f'### {lab}', '', _table(SHORT_HEADS, _short_rows(f['層別'][key])), '']
    p5 = f['上位1%除外']
    L += ['### 上位1%除外（P5）', '',
          f"- 合算 {p5['n']}回のうち R の上位 {p5['dropped']}件を除くと、平均 {_n(p5['avg_r_after'])}R・"
          f"総 {_n(p5['total_r_after'], '{:+.1f}')}R", '']

    # 3. 素朴ベースライン
    nv = r['naive']
    if not nv['available']:
        L += ['## 3. 素朴ベースライン（§5）', '', '- 実行していない（P4 は判定できないので不合格扱い）', '']
    else:
        L += _naive_section(nv, v)
    L += _rest_of_report(r, m, v, w, cf, f, pools, cmp_)
    return '\n'.join(L)


def _naive_section(nv, v):
    sel = nv['selection']
    return ['## 3. 素朴ベースライン（§5。p は回数だけで選ぶ）', '',
          _table(['p', f"{len(nv['seeds'])}シードの合算取引数の平均", 'fusion 比'],
                 [[p, _n(nv['mean_counts'][p], '{:.1f}'), _n(nv['mean_counts'][p] / sel['target'] if sel['target'] else NAN, '{:.2f}')]
                  for p in [str(x) for x in nv['grid']]]), '',
          f"- fusion の合算取引数 {sel['target']}回に最も近い p＝**{sel['p']}**（平均 {_n(sel['mean_count'], '{:.1f}')}回、"
          f"比 {_n(sel['ratio'], '{:.2f}')}）。±20% に{'入った' if sel['within_tol'] else '**入らなかった**'}。",
          f"- 選んだ p の{len(nv['seeds'])}シード（合算）：", '',
          _table(SHORT_HEADS, _short_rows(OrderedDict((f'seed {s}', x) for s, x in nv['chosen_seed_summaries'].items()))), '',
          f"- {len(nv['seeds'])}シードの平均R：平均 {_n(v['P4']['naive_mean'])}R、95パーセンタイル {_n(v['P4']['naive_p95'])}R"
          f"（numpy の線形補間）→ P4 は fusion ≥ {_n(v['P4'].get('need'))}R かつ ＞{_n(v['P4']['naive_p95'])}R が必要", '']


def _rest_of_report(r, m, v, w, cf, f, pools, cmp_):
    L = []
    # 4. DSR
    d = r['dsr']
    L += ['## 4. DSR（§6）', '',
          _table(['項目', '値'], [
              ['系列', f"合算の月次R（{d['months'][0]}〜{d['months'][1]}、取引のない月は0）"],
              ['T（月数）', d['T']], ['月次Rの平均・標準偏差', f"{_n(d['mean'])}・{_n(d['sd'], '{:.3f}')}"],
              ['SR̂', _n(d['sr'], '{:+.4f}')], ['γ₃（歪度）', _n(d['skew'], '{:+.3f}')], ['γ₄（尖度）', _n(d['kurt'], '{:.3f}')],
              ['V（開発期間の月次 SR の分散、ddof=1）', f"{_n(d['V'], '{:.6f}')}（{d['n_trials_for_V']}構成）"],
              ['N', d['N']], ['SR₀', _n(d['sr0'], '{:.4f}')], ['DSR', _n(d['dsr'], '{:.4f}')]]), '',
          f"- V の計算に使った構成ごとの SR（開発期間 {m['dev_window'][1][:7]}〜{m['dev_window'][2][:7]}、"
          f"{'・'.join(m['dev_window'][0])} 合算の月次R）：", '',
          _table(['構成', 'SR'], [[c, _n(x, '{:+.4f}')] for c, x in d['trial_sr'].items()]), '']

    # 5. 比較
    L += ['## 5. 比較（§8。銘柄年ブートストラップ seed=2024・10,000回、平均R差は ±1.645·SE）', '',
          f"銘柄年の数：{len(r['comparisons']['symbol_years'])}", '',
          _table(['比較対象', '回数', '平均R', '銘柄年あたり総R差 [90%区間]', '総R差（合計）', '平均R差 [90%区間]', '判定'],
                 [[c + ('' if x['judged'] else '（参考）'), cf[c]['合算']['trades'], _n(cf[c]['合算']['avg_r']),
                   f"{_n(x['per_symyear_diff'], '{:+.2f}')} {_ci(*x['per_symyear_ci90'])}", _n(x['total_diff'], '{:+.1f}'),
                   f"{_n(x['mean_diff'])} {_ci(*x['mean_diff_ci90'])}",
                   ('fusion の勝ち' if x['fusion_wins'] else '勝ちとは言えない')] for c, x in cmp_.items()]), '',
          '- 判定の対象は oku_only・kenjin_only・mincore_final。従来版EA（ma_slope）・4P-Score（fourp_score）は同じ方法で計算した参考値。',
          '']
    L += ['### 比較対象の成績（合算・プール別）', '',
          _table(_sheads(True), [_srow(c, cf[c]['合算'], True) for c in [MAIN] + COMPARE if c in cf]), '',
          _table(['構成'] + pools, [[c] + [f"{cf[c]['プール別'][p]['trades']}回 {_n(cf[c]['プール別'][p]['avg_r'])}R" for p in pools]
                                    for c in [MAIN] + COMPARE if c in cf]), '']

    # 6. アブレーション
    ab = r['ablations']
    L += [f"## 6. アブレーション（§9。Δ＝変種−fusion、Holm 補正 {ab['family_size']}変種・α=0.05）", '',
          _table(['変種', '回数', '平均R', 'Δ', 'SE_Δ', 'z', 'p', 'Holm 調整p', '有意', '符号 ' + '/'.join(pools), '符号（銘柄別）'],
                 [[c, x['trades'], _n(x['avg_r']), _n(x['delta']), _n(x['se_delta'], '{:.3f}'), _n(x['z'], '{:+.2f}'),
                   _n(x['p'], '{:.4f}'), _n(x['p_holm'], '{:.4f}'), '有意' if x['significant'] else '',
                   ' '.join(x['pool_signs'].values()), ' '.join(f'{ABBR.get(s, s)}{g}' for s, g in x['symbol_signs'].items())]
                  for c, x in ab['rows'].items()]), '',
          '- 銘柄の略称：' + '、'.join(f'{a}={s}' for s, a in ABBR.items() if s in m['symbols'])
          + '。符号は変種の平均R − fusion の平均R（· は計算できない）。',
          '- 結果は v1.1 の仮説として記録するだけで、v1.0 の既定は変えない。', '']

    # 7. 感度
    L += ['## 7. 感度（報告のみ。選択には使わない）', '',
          _table(['設定', '回数', '平均R', 'Δ', 'SE_Δ', 'z', '符号 ' + '/'.join(pools)],
                 [[c, x['trades'], _n(x['avg_r']), _n(x['delta']), _n(x['se_delta'], '{:.3f}'), _n(x['z'], '{:+.2f}'),
                   ' '.join(x['pool_signs'].values())] for c, x in r['sensitivity'].items()]), '']

    # 8. 副次
    L += ['## 8. 副次（合否に使わない）', '']
    if 'p2' in cf:
        p2 = cf['p2']
        L += ['### パターン②（M15）', '',
              _table(_sheads(True), [_srow('U-A＋U-B（SPEC §21 の副次評価）', p2['U-A＋U-B'], True)]
                     + [_srow(p, p2['プール別'][p], True) for p in pools]
                     + [_srow('合算（U-C を含む全プール。参考）', p2['合算'], True)]),
              '', '- SPEC §21 は②を「M15 データがある U-A・U-B で副次的に評価する」としている。合否には使わない。', '']
    L += [f"- ①-M15 降格：{r['secondary']['m15_downgrade']['note']}", '']

    # 9. 参考ウィンドウ
    L += ['## 9. 参考（既知データ。合否に使わない）', '',
          '既知の開発期間（既知IS）と既知のホールドアウト（既知HO。本番では内訳の既知HO-1＝4銘柄 2010〜2012、'
          '既知HO-2＝AUDUSD・USDCAD 2013〜2017 も）を、同じ実行から切り出したもの。', '']
    rows = []
    for c in [MAIN, 'mincore_final', 'oku_only', 'kenjin_only'] + BASELINES:
        if c in cf:
            for lab, s in cf[c]['参考'].items():
                rows.append(_srow(f'{c}／{lab}', s, True))
    L += [_table(_sheads(True), rows), '']
    if not m['dry_run']:
        L += ['- 既知の数値（SPEC §0.2・§20。MinCore FINAL＝mincore_raw。mincore_final とは接ぎ木の分だけ違う）：'
              '2010〜2012（4銘柄）357回 +16.4R PF1.06、AUDUSD・USDCAD 2013〜2017 313回 −55.5R PF0.76、'
              'IS 562回 +165.3R PF≈1.42。', '']
    for c in [MAIN, 'mincore_final']:
        if c in cf:
            for lab, blk in cf[c]['参考の銘柄別'].items():
                L += [f'### {c}／{lab}（銘柄別）', '', _table(SHORT_HEADS, _short_rows(blk)), '']

    # 10. 回数
    ck = r['checks']
    L += ['## 10. 回数の確認', '']
    e = ck.get('eurusd_10m_pools')
    if e:
        L.append(f"- EURUSD の10か月あたり回数（プール内、丸ごと入る暦月の連続10か月窓）：平均 {_n(e['mean'], '{:.1f}')}回"
                 f"（最小 {_n(e['min'], '{:d}')}〜最大 {_n(e['max'], '{:d}')}、窓 {e['windows']}個・{e['full_months']}か月）。"
                 f"単純換算 {_n(e['per10m_simple'], '{:.1f}')}回")
    e = ck.get('eurusd_10m_known_is')
    if e:
        L.append(f"- 同じ計算を既知IS で：平均 {_n(e['mean'], '{:.1f}')}回（{_n(e['min'], '{:d}')}〜{_n(e['max'], '{:d}')}、窓 {e['windows']}個）。"
                 f"SPEC §18 の照合表は {e['spec18'][0]}（{e['spec18'][1]}〜{e['spec18'][2]}）")
    bt = ck['bt_bundled']
    if bt.get('available'):
        L.append(f"- backtesting.py 同梱 EURUSD（{_ts(bt['first'], 10)}〜{_ts(bt['last'], 10)}、{bt['bars']}本"
                 + (f"、{bt['cut']} より前に切った" if bt['cut'] else '、ファイル全体') + f"）：fusion {bt['trades']}回"
                 f"（2017年分 {bt['trades_2017']}回。SPEC §18 の BT2017 は {bt['spec18_bt2017']}回）")
    else:
        L.append(f"- backtesting.py 同梱 EURUSD：読めなかった（{bt.get('note')}）")
    tr = ck['truncation']
    L.append(f"- 切断テスト（fusion、切った時点より前に決済した取引が一致するか）："
             + ('全部一致' if tr['all_match'] else ('不一致あり' if tr['all_match'] is False else '未実施')))
    L += ['', _table(['銘柄', '切断日', '比べた取引', '一致'],
                     [[x['symbol'], x['cut'], x['compared'], OK[x['match']]] for x in tr['rows']]), '']
    rec = ck['spec18_counts_known_is']
    L += ['### SPEC §18 照合表との回数照合（既知IS、回数だけ）', '',
          '本番は全期間を1本で走らせるので、2013年初めのウォームアップの違いで少しずれうる（許容 ±5%）。', '',
          _table(['構成', '照合表（4銘柄/EU/GU/EJ/XAU）', 'この実行', '±5% 以内'],
                 [[c, '/'.join(str(x) for x in y['spec18']), '/'.join(str(x) for x in y['got']), OK[y['within_5pct']]]
                  for c, y in rec.items()]), '']

    # 11. GAP_FALLBACK
    gp = f['GAP_FALLBACK']
    L += ['## 11. GAP_FALLBACK（fusion、合算）', '',
          f"- 合計 {gp['total']}件（FX {gp['fx']}件）。FX の年あたり {_n(w['gap_fallback']['per_year'], '{:.2f}')}件"
          f"（合算期間 {_n(w['gap_fallback']['years'], '{:.2f}')}年）",
          '- 銘柄別：' + '、'.join(f'{s} {c}' for s, c in gp['by_symbol'].items()),
          '- FX の年別：' + ('、'.join(f'{y}年 {c}' for y, c in gp['fx_by_year'].items()) or 'なし'), '']

    # 12. 全構成の一覧
    L += ['## 12. 全構成の成績一覧（合算）', '',
          _table(_sheads(True) + pools,
                 [_srow(c, cf[c]['合算'], True) + [_n(cf[c]['プール別'][p]['avg_r']) for p in pools] for c in cf]), '']

    # 付録
    L += ['## 付録：定義と解釈', '',
          '- R は fusion/broker.py の pnl_r（スプレッド込み、初期リスク＝1R）。t＝平均÷(標準偏差÷√n)、標準偏差は ddof=1。',
          '- プールの区間は「開始日0時」以上「終了日の翌日0時」未満（エントリー時刻＝約定した足の開始時刻、サーバー時間）。'
          '中点ちょうどのエントリーは後半に入れる。',
          '- 最大DD・最大連敗は、合算の取引をエントリー時刻順（同時刻は銘柄順）に並べた累積Rで数える（fusion/stats.py）。'
          'R≤0 の取引を負けとして数える。',
          '- 月ブロック・ブートストラップの「月」は取引のある暦月。抽出した月の全取引の平均Rを1回分とし、'
          'numpy.random.default_rng(12345) で10,000回。パーセンタイルは numpy の線形補間。',
          '- DSR の SR̂ と V の各 SR は、月次Rの平均÷標準偏差（ddof=1）。γ₃・γ₄ は標本モーメント（m3/m2^1.5、m4/m2²）。'
          'V の構成は VARIANTS（mincore_raw を除く、fusion・oku_only・kenjin_only・mincore_final を含む）と感度8つ。',
          '- 比較の銘柄年は「プール×銘柄×暦年」。取引がない銘柄年は総R=0。統計量は銘柄年あたりの総R差の平均で、'
          '90%区間は5／95パーセンタイル（総R差の区間はその銘柄年数倍）。',
          '- P4 の95パーセンタイルは20個の平均Rから numpy の線形補間で求め、fusion がそれを上回る（＞）ことを求める。',
          '- 警告「GAP_FALLBACK が FX で年1件を超える」は、合算の FX 全銘柄の件数を合算期間の年数（365.25日）で割った値で判定する。',
          '- 警告「EURUSD の10か月あたり回数」は、プール内に丸ごと入る暦月で作った連続10か月窓の平均（SPEC §18 の「10か月」列と同じ考え方）。',
          '- 「買いと売りの片方だけがマイナス」は合算の買い・売りそれぞれの平均Rの符号で判定する。', '']
    return L


def main(argv=None):
    ap = argparse.ArgumentParser(description='FUSION-CORE v1.0 の最終評価（PREREGISTRATION.md）')
    ap.add_argument('--data-dir', required=True, help='<SYM>_H1.csv と <SYM>_M15.csv のあるフォルダ')
    ap.add_argument('--out', required=True, help='出力フォルダ（results.json・trades.csv.gz・report.md）')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--dry-run', action='store_true', help='開発データの中の仮のプールで通り道だけを確かめる（数値は無意味）')
    a = ap.parse_args(argv)
    run_all(a.data_dir, a.out, workers=a.workers, dry_run=a.dry_run, log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
