"""最終評価スクリプト（fusion/final_eval.py）のテスト:  python -m unittest discover -s fusion/tests -t .

未接触データは使わない。合成データと、事前登録（PREREGISTRATION.md）の定義から手で計算した値だけで確かめる。
"""
import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np
import pandas as pd

from fusion import data as fd
from fusion import final_eval as fe
from fusion import strategy as fs


def make_trades(rows):
    """[(銘柄, エントリー時刻, R, 方向)] → final_eval が扱う形の取引 DataFrame"""
    df = pd.DataFrame([dict(symbol=s, entry_time=pd.Timestamp(t), exit_time=pd.Timestamp(t) + pd.Timedelta(hours=5),
                            direction=d, pnl_r=float(r), exit_reason='SL' if r < 0 else 'TRAIL')
                       for s, t, r, d in rows])
    df['sym_i'] = df['symbol'].map(fe.SYMBOLS.index)
    df['seq'] = np.arange(len(df))
    return df


def phi(x):
    """標準正規分布の累積分布（math.erf から。statistics.NormalDist とは独立に計算する）"""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def phi_inv(p):
    lo, hi = -12.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if phi(mid) < p else (lo, mid)
    return (lo + hi) / 2


# ---------------------------------------------------------------- プールの振り分け・中点
class TestPools(unittest.TestCase):
    def setUp(self):
        self.spec = fe.make_spec(dry_run=False)

    def where(self, sym, t):
        d = fe.assign(make_trades([(sym, t, 1.0, 1)]), self.spec)
        return d['pool'].iloc[0], d['half'].iloc[0], d['ref'].iloc[0]

    def test_pool_boundaries(self):
        cases = [
            ('EURUSD', '2005-03-31 23:00', ''), ('EURUSD', '2005-04-01 00:00', 'U-A'),
            ('EURUSD', '2008-12-31 23:00', 'U-A'), ('EURUSD', '2009-01-01 00:00', ''),
            ('XAUUSD', '2006-06-30 23:00', ''), ('XAUUSD', '2006-07-01 00:00', 'U-A'),   # 銘柄別の開始日
            ('XAUUSD', '2008-12-31 23:00', 'U-A'), ('XAUUSD', '2009-01-01 00:00', ''),
            ('AUDJPY', '2005-04-01 00:00', 'U-A'), ('AUDJPY', '2008-12-31 23:00', 'U-A'),
            ('AUDJPY', '2009-01-01 00:00', 'U-C'), ('AUDJPY', '2017-12-31 23:59', 'U-C'),
            ('AUDJPY', '2018-01-01 00:00', 'U-B'),
            ('AUDUSD', '2010-06-01 10:00', ''), ('USDCAD', '2017-12-29 23:00', ''),
            ('GBPUSD', '2017-12-31 23:59', ''), ('GBPUSD', '2018-01-01 00:00', 'U-B'),
            ('EURUSD', '2020-05-14 23:45', 'U-B'), ('EURUSD', '2020-05-15 00:00', ''),     # データ終端の翌日0時から外
        ]
        for sym, t, want in cases:
            self.assertEqual(self.where(sym, t)[0], want, (sym, t))

    def test_reference_windows(self):
        self.assertEqual(self.where('EURUSD', '2015-06-01 10:00'), ('', '', '既知IS'))
        self.assertEqual(self.where('XAUUSD', '2011-06-01 10:00'), ('', '', '既知HO|既知HO-1'))
        self.assertEqual(self.where('AUDUSD', '2014-06-02 10:00'), ('', '', '既知HO|既知HO-2'))
        self.assertEqual(self.where('EURUSD', '2012-12-31 23:00'), ('', '', '既知HO|既知HO-1'))
        self.assertEqual(self.where('USDCAD', '2013-01-01 00:00'), ('', '', '既知HO|既知HO-2'))
        self.assertEqual(self.where('XAUUSD', '2010-01-01 00:00')[2], '既知HO|既知HO-1')
        self.assertEqual(self.where('XAUUSD', '2009-12-31 23:00')[2], '')
        self.assertEqual(self.where('EURUSD', '2013-01-01 00:00'), ('', '', '既知IS'))
        self.assertEqual(self.where('AUDUSD', '2011-06-01 10:00'), ('', '', ''))     # どこにも入らない（集計しない）
        self.assertEqual(self.where('EURUSD', '2009-06-01 10:00'), ('', '', ''))
        self.assertEqual(self.where('AUDJPY', '2014-06-02 10:00')[2], '')             # U-C は参考に入れない

    def test_midpoints(self):
        mids = fe.pool_midpoints(self.spec)
        self.assertEqual(mids['U-A'], pd.Timestamp('2007-02-15 12:00'))
        self.assertEqual(mids['U-B'], pd.Timestamp('2019-03-09 12:00'))
        self.assertEqual(mids['U-C'], pd.Timestamp('2013-07-02 12:00'))
        self.assertEqual(fe.midpoint('2005-04-01', '2008-12-31'), pd.Timestamp('2007-02-15 12:00'))
        # 中点ちょうどは後半、その直前は前半。XAUUSD も U-A の中点で分ける
        self.assertEqual(self.where('EURUSD', '2007-02-15 11:00')[1], '前半')
        self.assertEqual(self.where('EURUSD', '2007-02-15 12:00')[1], '後半')
        self.assertEqual(self.where('XAUUSD', '2007-02-15 11:45')[1], '前半')
        self.assertEqual(self.where('XAUUSD', '2006-07-03 09:00')[1], '前半')
        self.assertEqual(self.where('AUDJPY', '2013-07-02 11:59')[1], '前半')
        self.assertEqual(self.where('AUDJPY', '2013-07-02 12:00')[1], '後半')
        self.assertEqual(self.where('USDCAD', '2019-03-09 12:00')[1], '後半')

    def test_registered_midpoint_mismatch_raises(self):
        with self.assertRaises(ValueError):
            fe.pool_midpoints(dict(self.spec, midpoints={'U-A': '2007-02-15 00:00'}))

    def test_overlapping_pools_raise(self):
        bad = dict(self.spec, pools=self.spec['pools'] + [('U-C', ['EURUSD'], '2008-01-01', '2009-12-31')])
        with self.assertRaises(ValueError):
            fe.assign(make_trades([('EURUSD', '2008-06-02 10:00', 1.0, 1)]), bad)

    def test_combined_span_and_dsr_months(self):
        lo, hi = fe.combined_span(self.spec)
        self.assertEqual((lo, hi), (pd.Timestamp('2005-04-01'), pd.Timestamp('2020-05-15')))
        self.assertEqual(self.spec['dsr_months'], ('2005-04', '2020-05'))
        self.assertEqual(len(pd.period_range(*self.spec['dsr_months'], freq='M')), 182)

    def test_dry_run_spec_stays_in_development_data(self):
        d = fe.make_spec(dry_run=True)
        self.assertEqual(d['symbols'], fe.FOUR)
        self.assertEqual(d['clip'], ('2013-01-01', '2018-01-01'))
        self.assertEqual(d['bt_cut'], '2018-01-01')
        for _, syms, a, b in d['pools'] + d['refs']:
            self.assertTrue(set(syms) <= set(fe.FOUR))
            self.assertGreaterEqual(pd.Timestamp(a), pd.Timestamp('2013-01-01'))
            self.assertLessEqual(fe.day_range(a, b)[1], pd.Timestamp('2018-01-01'))
        self.assertTrue(all(pd.Timestamp(c) < pd.Timestamp('2018-01-01') for c in d['cuts']))
        fe.pool_midpoints(d)

    def test_symbol_years(self):
        ranges = {s: (pd.Timestamp('2005-01-03'), pd.Timestamp('2020-05-14 20:00')) for s in fe.SYMBOLS}
        ranges['XAUUSD'] = (pd.Timestamp('2006-03-20'), pd.Timestamp('2020-05-14 20:00'))
        sy = fe.symbol_years(self.spec, fe.SYMBOLS, ranges)
        self.assertEqual(len(sy), 6 * 4 + 3 + 7 * 3 + 9)
        self.assertIn(('U-A', 'EURUSD', 2005), sy)
        self.assertNotIn(('U-A', 'XAUUSD', 2005), sy)
        self.assertEqual([k for k in sy if k[0] == 'U-C'], [('U-C', 'AUDJPY', y) for y in range(2009, 2018)])
        # データのない銘柄・年は入れない
        short = dict(ranges, GBPUSD=(pd.Timestamp('2005-01-03'), pd.Timestamp('2006-12-29')))
        sy2 = fe.symbol_years(self.spec, fe.SYMBOLS, short)
        self.assertNotIn(('U-A', 'GBPUSD', 2007), sy2)
        self.assertNotIn(('U-B', 'GBPUSD', 2018), sy2)
        self.assertIn(('U-A', 'GBPUSD', 2006), sy2)


# ---------------------------------------------------------------- 月ブロック・ブートストラップ
class TestMonthBlockBootstrap(unittest.TestCase):
    def sample(self):
        rng = np.random.default_rng(5)
        rows = []
        for i, m in enumerate(pd.date_range('2010-01-01', periods=30, freq='MS')):
            for k in range(1 + i % 4):                    # 同じ月に別の銘柄の取引を混ぜる（銘柄は問わない）
                rows.append((fe.SYMBOLS[k], m + pd.Timedelta(days=k, hours=3), float(rng.normal(0.1, 2.0)), 1))
        return make_trades(rows)

    def test_deterministic(self):
        df = self.sample()
        a, b = fe.month_block_ci(df), fe.month_block_ci(df)
        self.assertEqual(a, b)
        self.assertEqual((a['seed'], a['reps'], a['months']), (12345, 10000, 30))
        self.assertLess(a['lo'], df['pnl_r'].mean())
        self.assertGreater(a['hi'], df['pnl_r'].mean())

    def test_matches_definition(self):
        """定義どおりに書いた素直な版（同じ乱数の添字で月を選び、選んだ月の全取引の平均R）と一致する"""
        df = self.sample()
        got = fe.month_block_ci(df, reps=2000)
        per = df['entry_time'].dt.to_period('M')
        months = sorted(per.unique())
        groups = [df.loc[per == m, 'pnl_r'].tolist() for m in months]
        idx = np.random.default_rng(12345).integers(0, len(months), size=(2000, len(months)))
        means = []
        for row in idx:
            pooled = [r for j in row for r in groups[j]]
            means.append(sum(pooled) / len(pooled))
        lo, hi = np.percentile(means, [2.5, 97.5])
        self.assertAlmostEqual(got['lo'], lo, places=12)
        self.assertAlmostEqual(got['hi'], hi, places=12)

    def test_constant_r(self):
        df = make_trades([('EURUSD', f'2011-0{m}-03 10:00', 0.5, 1) for m in range(1, 7)])
        ci = fe.month_block_ci(df)
        self.assertAlmostEqual(ci['lo'], 0.5)
        self.assertAlmostEqual(ci['hi'], 0.5)

    def test_empty(self):
        ci = fe.month_block_ci(make_trades([('EURUSD', '2011-01-03', 1.0, 1)]).iloc[:0])
        self.assertTrue(math.isnan(ci['lo']))


# ---------------------------------------------------------------- DSR
class TestDSR(unittest.TestCase):
    X = [2, -1, 0, 3, -2, 1, 4, -1]

    def test_paper_example(self):
        """Bailey & López de Prado (2014) の数値例: 年率 SR̂=2.5、T=1250日、γ₃=−3、γ₄=10、N=100、V=1/2（年率）→ DSR≈0.9004"""
        sr0 = fe.expected_max_sr(0.5 / 250, n=100)
        self.assertAlmostEqual(sr0, 0.1132, places=4)
        self.assertAlmostEqual(fe.deflated_sharpe(2.5 / math.sqrt(250), 1250, -3.0, 10.0, sr0), 0.9004, places=4)

    def test_sr0_constant_n250(self):
        k = (1 - 0.5772156649) * phi_inv(1 - 1 / 250) + 0.5772156649 * phi_inv(1 - 1 / (250 * math.e))
        self.assertAlmostEqual(fe.expected_max_sr(1.0), k, places=10)
        self.assertAlmostEqual(fe.expected_max_sr(0.04), 0.2 * k, places=10)
        self.assertAlmostEqual(k, 2.8376770761, places=8)

    def test_hand_computed_moments(self):
        # 平均 3/4、偏差平方和 63/2 → 標準偏差(ddof=1)=√(9/2)、SR=(3/4)/√(9/2)=√(1/8)
        self.assertAlmostEqual(fe.sharpe(self.X), math.sqrt(1 / 8), places=12)
        # m2=63/16、m3=63/32、m4=6909/256 → γ₃=m3/m2^1.5=2/√63、γ₄=m4/m2²=47/27
        g3, g4 = fe.moments(self.X)
        self.assertAlmostEqual(g3, 2 / math.sqrt(63), places=12)
        self.assertAlmostEqual(g4, 47 / 27, places=12)
        g3n, g4n = fe.moments(np.random.default_rng(1).normal(size=200000))
        self.assertAlmostEqual(g3n, 0.0, delta=0.03)
        self.assertAlmostEqual(g4n, 3.0, delta=0.05)              # 正規分布で3になる定義

    def test_hand_computed_dsr(self):
        trials = {'a': 0.1, 'b': 0.3, 'c': 0.2, 'd': float('nan')}  # 分散(ddof=1)=0.01。NaN は除く
        blk = fe.dsr_block(self.X, trials)
        self.assertEqual(blk['n_trials_for_V'], 3)
        self.assertAlmostEqual(blk['V'], 0.01, places=12)
        sr, g3, g4, t = math.sqrt(1 / 8), 2 / math.sqrt(63), 47 / 27, 8
        k = (1 - 0.5772156649) * phi_inv(1 - 1 / 250) + 0.5772156649 * phi_inv(1 - 1 / (250 * math.e))
        sr0 = 0.1 * k
        want = phi((sr - sr0) * math.sqrt(t - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
        self.assertAlmostEqual(blk['sr0'], sr0, places=10)
        self.assertAlmostEqual(blk['dsr'], want, places=10)
        self.assertEqual(blk['T'], 8)

    def test_monthly_r(self):
        df = make_trades([('EURUSD', '2013-01-05 10:00', 1.0, 1), ('XAUUSD', '2013-01-20 10:00', -0.5, -1),
                          ('GBPUSD', '2013-03-02 10:00', 2.0, 1)])
        s = fe.monthly_r(df, '2013-01', '2013-04')
        self.assertEqual(s.tolist(), [0.5, 0.0, 2.0, 0.0])         # 取引のない月は0
        with self.assertRaises(ValueError):
            fe.monthly_r(df, '2013-02', '2013-04')                 # 期間外の取引は黙って落とさない


# ---------------------------------------------------------------- Holm・素朴ベースラインの p・上位1%除外
class TestHolm(unittest.TestCase):
    def test_known_example(self):
        h = fe.holm({'a': 0.01, 'b': 0.04, 'c': 0.03, 'd': 0.005})
        self.assertEqual([h[k]['significant'] for k in 'abcd'], [True, False, False, True])
        for k, want in (('d', 0.02), ('a', 0.03), ('c', 0.06), ('b', 0.06)):
            self.assertAlmostEqual(h[k]['p_holm'], want, places=12)
        self.assertEqual([h[k]['rank'] for k in 'dacb'], [1, 2, 3, 4])

    def test_step_down_stops(self):
        # 3番目で止まったら、4番目は単独の閾値（α/1）を満たしても有意にしない
        h = fe.holm({'a': 0.001, 'b': 0.002, 'c': 0.03, 'd': 0.04})
        self.assertEqual([h[k]['significant'] for k in 'abcd'], [True, True, False, False])

    def test_nan_as_one_and_family_size(self):
        p = {f'v{i}': 0.5 for i in range(26)}                        # アブレーションの族と同じ26個
        p['v0'] = 0.05 / 26 * 0.999
        p['v1'] = float('nan')
        h = fe.holm(p)
        self.assertTrue(h['v0']['significant'])
        self.assertAlmostEqual(h['v0']['threshold'], 0.05 / 26)
        self.assertEqual(h['v1']['p_holm'], 1.0)
        self.assertFalse(h['v1']['significant'])
        h2 = fe.holm(dict(p, v0=0.05 / 26 * 1.001))
        self.assertFalse(h2['v0']['significant'])


class TestNaiveSelection(unittest.TestCase):
    def test_nearest_p_by_counts_only(self):
        counts = {0.005: 300.0, 0.01: 600.0, 0.015: 850.0, 0.02: 1100.0, 0.03: 1500.0, 0.05: 2100.0, 0.08: 2600.0}
        s = fe.choose_naive_p(counts, 1000)
        self.assertEqual(s['p'], 0.02)
        self.assertTrue(s['within_tol'])
        self.assertAlmostEqual(s['ratio'], 1.1)
        s = fe.choose_naive_p(counts, 700)
        self.assertEqual(s['p'], 0.01)
        self.assertTrue(s['within_tol'])                           # |600-700| = 100 ≤ 140

    def test_outside_tolerance_is_reported(self):
        s = fe.choose_naive_p({0.005: 300.0, 0.01: 600.0}, 1000)
        self.assertEqual(s['p'], 0.01)
        self.assertFalse(s['within_tol'])
        self.assertTrue(fe.choose_naive_p({0.01: 800.0}, 1000)['within_tol'])     # ちょうど −20%
        self.assertFalse(fe.choose_naive_p({0.01: 799.0}, 1000)['within_tol'])

    def test_tie_takes_smaller_p(self):
        self.assertEqual(fe.choose_naive_p({0.02: 900.0, 0.03: 1100.0}, 1000)['p'], 0.02)


class TestTopOnePercent(unittest.TestCase):
    def test_count_is_ceil(self):
        for n, k in ((0, 0), (1, 1), (99, 1), (100, 1), (101, 2), (200, 2), (201, 3), (1399, 14), (1400, 14), (1401, 15)):
            self.assertEqual(fe.drop_top(np.zeros(n))[0], k, n)

    def test_removes_largest(self):
        r = np.r_[np.full(150, -0.2), [30.0, 25.0, 1.0]]          # n=153 → 2件除外
        k, rest = fe.drop_top(r)
        self.assertEqual(k, 2)
        self.assertEqual(sorted(rest)[-1], 1.0)
        p5 = fe.judge_p5(r)
        self.assertFalse(p5['ok'])
        self.assertAlmostEqual(p5['avg_r_after'], (150 * -0.2 + 1.0) / 151)
        self.assertTrue(fe.judge_p5(np.r_[np.zeros(99), 5.0])['ok'])          # 除いた後の平均が0でも合格（≥0）
        self.assertFalse(fe.judge_p5(np.array([3.0]))['ok'])                   # 何も残らないときは判定できない


# ---------------------------------------------------------------- 合格基準・警告
class TestCriteria(unittest.TestCase):
    def s(self, avg, t, lo, n=500):
        return dict(trades=n, avg_r=avg, t_stat=t, ci95_lo=lo, ci95_hi=lo + 0.2)

    def test_p1(self):
        self.assertTrue(fe.judge_p1(self.s(0.1, 2.0, 0.001))['ok'])           # t ちょうど 2.0 は合格
        self.assertFalse(fe.judge_p1(self.s(0.1, 1.99, 0.01))['ok'])
        self.assertFalse(fe.judge_p1(self.s(0.1, 2.5, 0.0))['ok'])            # 区間の下限は ＞0
        self.assertFalse(fe.judge_p1(self.s(0.0, 2.5, 0.01))['ok'])
        self.assertFalse(fe.judge_p1(self.s(float('nan'), float('nan'), float('nan'), n=0))['ok'])

    def test_p2(self):
        syms = {'EURUSD': (100, 0.1), 'GBPUSD': (80, 0.05), 'EURJPY': (60, -0.1), 'AUDUSD': (90, 0.2),
                'USDCAD': (70, -0.3), 'AUDJPY': (29, -1.0)}                    # AUDJPY は30回未満で対象外
        r = fe.judge_p2({'U-A': 0.1, 'U-B': -0.1, 'U-C': 0.05}, syms)
        self.assertTrue(r['ok'])
        self.assertEqual(r['eligible_symbols'], ['EURUSD', 'GBPUSD', 'EURJPY', 'AUDUSD', 'USDCAD'])
        self.assertAlmostEqual(r['frac'], 0.6)                                   # ちょうど60%は合格
        self.assertFalse(fe.judge_p2({'U-A': 0.1, 'U-B': -0.1, 'U-C': 0.0}, syms)['ok'])   # 平均R＞0 は1つだけ
        self.assertFalse(fe.judge_p2({'U-A': 0.1, 'U-B': 0.1, 'U-C': float('nan')},
                                     dict(syms, GBPUSD=(80, -0.05)))['ok'])                # 2/5=40%
        self.assertFalse(fe.judge_p2({'U-A': 0.1, 'U-B': 0.1}, {'EURUSD': (10, 0.5)})['ok'])  # 対象銘柄なし

    def test_p3(self):
        self.assertTrue(fe.judge_p3(0.01, 0.2)['ok'])
        self.assertFalse(fe.judge_p3(0.0, 0.2)['ok'])
        self.assertFalse(fe.judge_p3(0.3, -0.01)['ok'])

    def test_p4(self):
        seeds = list(np.linspace(-0.1, 0.09, 20))
        mean, p95 = float(np.mean(seeds)), float(np.percentile(seeds, 95))
        r = fe.judge_p4(mean + 0.10, seeds)
        self.assertAlmostEqual(r['naive_mean'], mean)
        self.assertAlmostEqual(r['naive_p95'], p95)
        self.assertTrue(r['ok'])                                                  # 平均＋0.10 ちょうどは合格（≥）
        self.assertFalse(fe.judge_p4(mean + 0.0999, seeds)['ok'])
        wide = [0.0] * 19 + [1.0]                                                 # 95%点が平均＋0.10 より上
        self.assertAlmostEqual(fe.judge_p4(0.2, wide)['naive_p95'], 0.05)        # 19.05番目（線形補間）
        self.assertTrue(fe.judge_p4(0.2, wide)['ok'])
        self.assertFalse(fe.judge_p4(0.1, [0.0] * 18 + [0.2, 0.3])['ok'])        # 平均0.025＋0.10 未満
        self.assertFalse(fe.judge_p4(0.5, seeds[:-1] + [float('nan')])['ok'])    # 計算できないシードがある

    def test_p6(self):
        self.assertTrue(fe.judge_p6(0.90)['ok'])
        self.assertFalse(fe.judge_p6(0.8999)['ok'])
        self.assertFalse(fe.judge_p6(float('nan'))['ok'])

    def test_warnings(self):
        self.assertTrue(fe.warn_long_short(0.1, -0.05)['fire'])
        self.assertTrue(fe.warn_long_short(-0.1, 0.05)['fire'])
        self.assertFalse(fe.warn_long_short(-0.1, -0.05)['fire'])
        self.assertFalse(fe.warn_long_short(0.1, 0.0)['fire'])
        self.assertTrue(fe.warn_gap(16, 15.12)['fire'])
        self.assertFalse(fe.warn_gap(15, 15.12)['fire'])
        self.assertTrue(fe.warn_ten_month(14.9)['fire'])
        self.assertFalse(fe.warn_ten_month(15.0)['fire'])


# ---------------------------------------------------------------- 比較・アブレーション・10か月窓
class TestComparisonAndAblation(unittest.TestCase):
    def test_compare(self):
        spec = fe.make_spec(dry_run=False)
        sy = [('U-A', 'EURUSD', 2006), ('U-A', 'EURUSD', 2007), ('U-B', 'GBPUSD', 2018)]
        f = fe.chrono(fe.assign(make_trades([('EURUSD', '2006-03-01 10:00', 1.0, 1), ('EURUSD', '2006-05-01 10:00', 2.0, 1),
                                             ('EURUSD', '2007-03-01 10:00', -1.0, -1)]), spec))
        v = fe.chrono(fe.assign(make_trades([('EURUSD', '2006-03-01 10:00', 0.5, 1),
                                             ('GBPUSD', '2018-03-01 10:00', -2.0, 1)]), spec))
        fs_, vs_ = fe.summary(f), fe.summary(v)
        r = fe.compare(f, v, sy, fs_, vs_)
        d = np.array([3.0 - 0.5, -1.0 - 0.0, 0.0 - (-2.0)])                 # 取引のない銘柄年は総R=0
        self.assertAlmostEqual(r['total_diff'], d.sum())
        self.assertAlmostEqual(r['per_symyear_diff'], d.mean())
        boot = d[np.random.default_rng(2024).integers(0, 3, size=(10000, 3))].mean(axis=1)
        lo, hi = np.percentile(boot, [5, 95])
        self.assertAlmostEqual(r['per_symyear_ci90'][0], lo, places=12)
        self.assertAlmostEqual(r['per_symyear_ci90'][1], hi, places=12)
        delta = np.mean([1.0, 2.0, -1.0]) - np.mean([0.5, -2.0])
        se = math.sqrt(np.var([1.0, 2.0, -1.0], ddof=1) / 3 + np.var([0.5, -2.0], ddof=1) / 2)
        self.assertAlmostEqual(r['mean_diff'], delta)
        self.assertAlmostEqual(r['mean_diff_ci90'][0], delta - 1.645 * se)
        self.assertAlmostEqual(r['mean_diff_ci90'][1], delta + 1.645 * se)
        self.assertEqual(r['fusion_wins'], bool(lo > 0 and delta - 1.645 * se > -0.10))
        with self.assertRaises(ValueError):                                     # 一覧にない銘柄年の取引は落とさない
            fe.compare(f, v, sy[1:], fs_, vs_)

    def test_compare_win_rule(self):
        spec = fe.make_spec(dry_run=False)
        sy = [('U-A', 'EURUSD', y) for y in (2005, 2006, 2007, 2008)]
        rows_f = [('EURUSD', f'{y}-0{m}-02 10:00', r, 1) for y in (2005, 2006, 2007, 2008) for m, r in ((5, 1.0), (6, 0.8))]
        rows_v = [('EURUSD', f'{y}-0{m}-02 10:00', r, 1) for y in (2005, 2006, 2007, 2008) for m, r in ((5, 0.9), (6, 0.7))]
        f = fe.chrono(fe.assign(make_trades(rows_f), spec))
        v = fe.chrono(fe.assign(make_trades(rows_v), spec))
        r = fe.compare(f, v, sy, fe.summary(f), fe.summary(v))
        self.assertAlmostEqual(r['per_symyear_ci90'][0], 0.2)                  # どの銘柄年も +0.2R
        self.assertTrue(r['fusion_wins'])

    def test_delta_test(self):
        f = dict(avg_r=0.10, se=0.03)
        v = dict(avg_r=0.02, se=0.04)
        r = fe.delta_test(f, v)
        self.assertAlmostEqual(r['delta'], -0.08)
        self.assertAlmostEqual(r['se_delta'], 0.05)
        self.assertAlmostEqual(r['z'], -1.6)
        self.assertAlmostEqual(r['p'], 2 * (1 - phi(1.6)), places=10)

    def test_ten_month(self):
        rows = []
        for i, m in enumerate(pd.date_range('2013-01-01', periods=24, freq='MS')):
            rows += [('EURUSD', m + pd.Timedelta(days=1, hours=k), 1.0, 1) for k in range(i + 1)]   # i+1 回/月
        df = make_trades(rows)
        r = fe.ten_month(df, [fe.day_range('2013-01-01', '2014-12-31')])
        sums = [sum(range(i + 1, i + 11)) for i in range(15)]
        self.assertEqual((r['windows'], r['full_months'], r['min'], r['max']), (15, 24, min(sums), max(sums)))
        self.assertAlmostEqual(r['mean'], float(np.mean(sums)))
        r2 = fe.ten_month(df, [fe.day_range('2013-01-01', '2014-12-14')])      # 途中で終わる月は窓に使わない
        self.assertEqual((r2['full_months'], r2['windows']), (23, 14))
        r3 = fe.ten_month(df, [fe.day_range('2013-01-01', '2013-06-30'), fe.day_range('2013-07-01', '2014-12-31')])
        self.assertEqual(r3['windows'], 15)                                    # つながった区間は1本
        r4 = fe.ten_month(df, [fe.day_range('2013-01-01', '2013-10-31'), fe.day_range('2014-01-01', '2014-10-31')])
        self.assertEqual(r4['windows'], 2)                                     # 離れた区間は別々
        self.assertEqual(fe.ten_month(df, [fe.day_range('2013-01-01', '2013-08-31')])['windows'], 0)


# ---------------------------------------------------------------- 構成の一覧・JSON
class TestConfigsAndOutput(unittest.TestCase):
    def test_config_lists(self):
        self.assertEqual(fe.SYMBOLS, ['EURUSD', 'GBPUSD', 'EURJPY', 'AUDUSD', 'USDCAD', 'AUDJPY', 'XAUUSD'])
        self.assertEqual(len(fe.ABLATIONS), 26)
        for c in ('fusion', 'mincore_raw', 'oku_only', 'kenjin_only', 'mincore_final'):
            self.assertNotIn(c, fe.ABLATIONS)
        self.assertEqual(len(fe.V_SET), 38)
        self.assertIn('fusion', fe.V_SET)
        for c in ('mincore_raw', 'ma_slope', 'fourp_score', 'p2'):
            self.assertNotIn(c, fe.V_SET)
        cfgs = fe.all_configs()
        self.assertEqual(len(cfgs), 1 + 5 + 26 + 8 + 1 + 7 * 20)
        self.assertEqual(len(set(cfgs)), len(cfgs))
        for c in cfgs:
            if c.startswith('naive'):
                continue
            self.assertTrue(c in fe.BASELINES or c == 'p2' or c in fs.VARIANTS or c in fs.SENSITIVITY, c)
        for p in fe.NAIVE_P:
            self.assertEqual(fs.config(fe.naive_name(p, 7)), dict(entry='naive', naive_p=p, naive_seed=7))

    def test_clean(self):
        out = fe.clean({'a': float('nan'), 'b': np.float64(float('inf')), 'c': np.int64(3), 'd': np.bool_(True),
                        'e': pd.Timestamp('2020-01-02 03:00'), 'f': (1.5, None), 3: 'x'})
        self.assertEqual(out, {'a': None, 'b': 'inf', 'c': 3, 'd': True, 'e': '2020-01-02T03:00:00', 'f': [1.5, None],
                               '3': 'x'})
        json.dumps(out, allow_nan=False)


# ---------------------------------------------------------------- 全体の通し（合成データ・小さな構成）
def synthetic_m15(start, days, seed, scale=1.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days * 96, freq='15min')
    idx = idx[idx.dayofweek < 5]
    n = len(idx)
    drift = np.repeat(rng.choice([-1, 1], size=n // 1200 + 1) * 0.00006, 1200)[:n]
    c = 1.2 + np.cumsum(drift + rng.normal(0, 0.00045, n)) + 0.0004 * np.sin(np.arange(n) / 36.0)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 0.00035, n)
    lo = np.minimum(o, c) - rng.uniform(0, 0.00035, n)
    df = pd.DataFrame({'Open': o * scale, 'High': h * scale, 'Low': lo * scale, 'Close': c * scale, 'Volume': 1.0},
                      index=idx)
    df.index.name = 'Time'
    return df


E2E_SPEC = dict(
    dry_run=True, symbols=['EURUSD', 'EURJPY'], clip=None, bt_cut='2018-01-01',
    pools=[('U-A', ['EURUSD'], '2015-02-01', '2015-03-31'), ('U-A', ['EURJPY'], '2015-02-15', '2015-03-31'),
           ('U-B', ['EURUSD', 'EURJPY'], '2015-05-01', '2015-07-10'), ('U-C', ['EURJPY'], '2015-04-01', '2015-04-30')],
    periods={'U-A': ('2015-02-01', '2015-03-31'), 'U-B': ('2015-05-01', '2015-07-10'), 'U-C': ('2015-04-01', '2015-04-30')},
    midpoints=None,
    refs=[('既知IS', ['EURUSD', 'EURJPY'], '2015-01-01', '2015-07-31'), ('既知HO', ['EURUSD'], '2015-04-01', '2015-04-30')],
    dsr_months=('2015-02', '2015-07'), dev=(['EURUSD', 'EURJPY'], '2015-01-01', '2015-07-31'), cuts=['2015-05-01'])
E2E_CONFIGS = ['fusion', 'oku_only', 'mincore_final', 'ma_slope', 'F-slope', 'F+G3', 'S:N_BIG=10', 'p2'] + \
              [fe.naive_name(p, s) for p in (0.02, 0.05) for s in (0, 1)]


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='final_eval_test_')
        cls.data = os.path.join(cls.tmp, 'data')
        os.makedirs(cls.data)
        for sym, seed, scale in (('EURUSD', 1, 1.0), ('EURJPY', 2, 100.0)):
            m15 = synthetic_m15('2015-01-05', 210, seed, scale)
            m15.to_csv(os.path.join(cls.data, f'{sym}_M15.csv'), float_format='%.6f')
            fd.resample(m15, 'H1').to_csv(os.path.join(cls.data, f'{sym}_H1.csv'), float_format='%.6f')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_once(self, name):
        out = os.path.join(self.tmp, name)
        res = fe.run_all(self.data, out, workers=1, spec=E2E_SPEC, configs=E2E_CONFIGS, naive_p=[0.02, 0.05],
                         naive_seeds=[0, 1], log=lambda s: None)
        return out, res

    def test_outputs_are_complete_and_deterministic(self):
        out1, res = self.run_once('out1')
        out2, _ = self.run_once('out2')
        for name in ('results.json', 'trades.csv.gz', 'report.md'):
            with open(os.path.join(out1, name), 'rb') as a, open(os.path.join(out2, name), 'rb') as b:
                self.assertEqual(a.read(), b.read(), name)
        with open(os.path.join(out1, 'report.md'), encoding='utf-8') as fh:
            report = fh.read()
        self.assertTrue(report.startswith('# 【ドライラン：数値は無意味】'))
        self.assertIn('## 結論', report)
        with open(os.path.join(out1, 'results.json'), encoding='utf-8') as fh:
            js = json.load(fh)
        self.assertTrue(js['meta']['dry_run'])
        self.assertFalse(js['meta']['prereg_naive'])
        for k in ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'pass', 'warnings'):
            self.assertIn(k, js['verdict'])
        self.assertEqual(set(js['configs']), set(c for c in E2E_CONFIGS if not c.startswith('naive')))
        self.assertTrue(js['checks']['truncation']['all_match'])
        self.assertEqual(js['ablations']['family_size'], 2)
        self.assertIn(js['naive']['selection']['p'], (0.02, 0.05))
        tr = pd.read_csv(os.path.join(out1, 'trades.csv.gz'), keep_default_na=False)
        self.assertEqual(list(tr.columns[:4]), ['config', 'pool', 'half', 'ref'])
        self.assertTrue(set(tr['config']) <= set(E2E_CONFIGS))
        self.assertIn('fusion', set(tr['config']))
        fu = tr[(tr['config'] == 'fusion') & (tr['pool'] != '')]
        self.assertEqual(len(fu), js['configs']['fusion']['合算']['trades'])
        self.assertAlmostEqual(fu['pnl_r'].sum(), js['configs']['fusion']['合算']['total_r'], places=9)
        self.assertTrue(set(tr['pool']) <= {'', 'U-A', 'U-B', 'U-C'})
        self.assertTrue(((tr['pool'] == '') == (tr['half'] == '')).all())
        # プールの振り分けを CSV からやり直しても同じになる
        again = fe.assign(make_trades([(s, t, r, d) for s, t, r, d in
                                       zip(tr['symbol'], tr['entry_time'], tr['pnl_r'], tr['direction'])]), E2E_SPEC)
        self.assertEqual(again['pool'].tolist(), tr['pool'].tolist())
        self.assertEqual(again['half'].tolist(), tr['half'].tolist())


if __name__ == '__main__':
    unittest.main()
