"""FUSION-CORE（fusion/strategy.py）のテスト:  python -m unittest discover -s fusion/tests -t .

実データの照合（ゴールデン CSV）は、データがあるときだけ走る:
  - backtesting.py 同梱の EURUSD（pip install backtesting）
  - 環境変数 FUSION_DATA_DIR に EURUSD_H1.csv（OANDA 2013〜2017、fusion.data.prepare_oanda で作ったもの）
"""
import os
import unittest
from datetime import date

import numpy as np
import pandas as pd

from fusion import data as fd
from fusion import strategy as fs

GOLDEN = os.path.join(os.path.dirname(__file__), 'golden')
COLS = ['symbol', 'entry_time', 'exit_time', 'direction', 'entry', 'initial_sl', 'exit_reason', 'bars_held',
        'm_pattern', 'm_score', 'm_rel', 'm_n_sup', 'm_rr_cf', 'm_r_atr']


def trending_h1(n=6000, seed=3):
    """トレンドと押し・戻りを繰り返す合成 H1（平日のみ）"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2015-01-05', periods=int(n * 1.5), freq='1h')
    idx = idx[idx.dayofweek < 5][:n]
    drift = np.repeat(rng.choice([-1, 1], size=n // 300 + 1) * 0.00012, 300)[:n]
    wave = 0.0006 * np.sin(np.arange(n) / 9.0)
    c = 1.2 + np.cumsum(drift + rng.normal(0, 0.0009, n)) + wave
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 0.0007, n)
    l = np.minimum(o, c) - rng.uniform(0, 0.0007, n)
    return pd.DataFrame({'Open': o, 'High': h, 'Low': l, 'Close': c, 'Volume': 1.0}, index=idx)


def as_golden(trades):
    df = pd.DataFrame(trades)[COLS]
    for c in ('entry_time', 'exit_time'):
        df[c] = pd.to_datetime(df[c]).dt.strftime('%Y-%m-%d %H:%M:%S')
    return df.reset_index(drop=True)


class TestGolden(unittest.TestCase):
    def check(self, trades, path):
        g = pd.read_csv(path)
        df = as_golden(trades)
        self.assertEqual(len(df), len(g))
        for c in COLS:
            if g[c].dtype.kind in 'fi':
                np.testing.assert_allclose(df[c].astype(float), g[c].astype(float), atol=1e-6, err_msg=c)
            else:
                self.assertTrue((df[c].astype(str) == g[c].astype(str)).all(), c)

    def test_backtesting_eurusd_2017(self):
        try:
            bt = fd.load_backtesting_eurusd()
        except FileNotFoundError:
            self.skipTest('backtesting 未インストール')
        trades, _ = fs.run_h1(bt[bt.index < '2018-01-01'], 'EURUSD')
        self.check(trades, os.path.join(GOLDEN, 'golden_bt_eurusd_2017.csv'))

    def test_oanda_eurusd_is(self):
        d = os.environ.get('FUSION_DATA_DIR')
        if not d or not os.path.exists(os.path.join(d, 'EURUSD_H1.csv')):
            self.skipTest('FUSION_DATA_DIR（EURUSD_H1.csv）がない')
        h1 = fd.load_prepared('EURUSD', 'H1', d)
        h1 = h1[(h1.index >= '2013-01-01') & (h1.index < '2018-01-01')]
        trades, _ = fs.run_h1(h1, 'EURUSD')
        self.check(trades, os.path.join(GOLDEN, 'golden_oanda_eurusd_is.csv'))


class TestCausality(unittest.TestCase):
    def test_truncation_does_not_change_past_trades(self):
        """データを途中で切っても、切った時点より前の判定・約定・決済は変わらない（先読みなし）"""
        h1 = trending_h1()
        for variant in ('fusion', 'oku_only', 'kenjin_only', 'F+p3', 'naive:p=0.05:seed=1'):
            full, _ = fs.run_h1(h1, 'EURUSD', fs.config(variant))
            self.assertGreater(len(full), 5, variant)
            for cut in (2500, 4100):
                part, _ = fs.run_h1(h1.iloc[:cut], 'EURUSD', fs.config(variant))
                cut_time = h1.index[cut - 1]
                a = [t for t in full if t['exit_time'] < cut_time]
                b = [t for t in part if t['exit_time'] < cut_time]
                keys = ('entry_time', 'direction', 'entry', 'initial_sl', 'exit_time', 'pnl_r', 'exit_reason')
                self.assertEqual([tuple(t[k] for k in keys) for t in a], [tuple(t[k] for k in keys) for t in b],
                                 f'{variant} cut={cut}')

    def test_orders_fill_after_signal_bar(self):
        h1 = trending_h1()
        trades, _ = fs.run_h1(h1, 'EURUSD')
        pos = {t: i for i, t in enumerate(h1.index)}
        for t in trades:
            self.assertGreaterEqual(pos[t['entry_time']], 92)
            # 逆指値の約定価格は、約定した足の値幅（＋スプレッド）の中にある
            bar = h1.loc[t['entry_time']]
            mid = t['entry'] - t['direction'] * fs.S_NOM['EURUSD'] / 2
            self.assertLessEqual(mid, bar['High'] + 1e-12)
            self.assertGreaterEqual(mid, bar['Low'] - 1e-12)


class TestCalendarAndConfig(unittest.TestCase):
    def test_good_friday(self):
        for y, gf in ((2013, date(2013, 3, 29)), (2016, date(2016, 3, 25)), (2019, date(2019, 4, 19))):
            closed, early = fs.calendar_sets('XAUUSD', [y])
            self.assertIn(gf, closed)
            self.assertNotIn(gf, fs.calendar_sets('EURUSD', [y])[0])
        closed, early = fs.calendar_sets('XAUUSD', [2017])
        self.assertIn(date(2017, 11, 24), early)        # 感謝祭の翌金曜
        self.assertIn(date(2017, 7, 4), early)
        self.assertIn(date(2017, 12, 25), closed)

    def test_time_rules(self):
        idx = pd.date_range('2017-12-20', '2017-12-27', freq='1h')
        idx = idx[idx.dayofweek < 5]
        no_new, flat, roll, gap = fs.time_rules(idx, 'EURUSD', dict(fs.DEFAULT_SW), pd.Timedelta(hours=1), 12)
        at = {t: i for i, t in enumerate(idx)}
        self.assertTrue(no_new[at[pd.Timestamp('2017-12-22 19:00')]])     # 金曜 20時確定 → 新規停止
        self.assertFalse(flat[at[pd.Timestamp('2017-12-22 20:00')]])
        self.assertTrue(flat[at[pd.Timestamp('2017-12-22 21:00')]])       # 金曜 22時確定 → 全決済
        self.assertTrue(flat[at[pd.Timestamp('2017-12-25 05:00')]])       # 休場日
        self.assertTrue(roll[at[pd.Timestamp('2017-12-20 22:00')]])       # 23時確定 → ロールオーバー
        self.assertTrue(roll[at[pd.Timestamp('2017-12-20 23:00')]])
        self.assertFalse(roll[at[pd.Timestamp('2017-12-21 00:00')]])
        self.assertTrue(gap[at[pd.Timestamp('2017-12-25 00:00')]])        # 週末明け（12時間以上の空き）

    def test_registered_variants(self):
        for name in ('fusion', 'oku_only', 'kenjin_only', 'mincore_final', 'mincore_raw', 'F-slope', 'F-G2', 'F-HH',
                     'F-stop', 'F-trail', 'F-weekend', 'F-rcap', 'F-slfloor', 'F-onefill', 'F-rollover',
                     'F-calendar', 'F+G3', 'F+d1', 'F+d1soft', 'F+gap', 'F+clear', 'F+clear_d1', 'F+support',
                     'F+slnode', 'F+partial', 'F+be', 'F+trail1h', 'F+p3', 'F~dowP', 'F+h1trans', 'F~conv'):
            self.assertIn(name, fs.VARIANTS)
        self.assertEqual(len(fs.SENSITIVITY), 8)
        self.assertEqual(fs.config('naive:p=0.03:seed=7'), dict(entry='naive', naive_p=0.03, naive_seed=7))

    def test_naive_baseline(self):
        h1 = trending_h1()
        a, _ = fs.run_h1(h1, 'EURUSD', fs.config('naive:p=0.05:seed=1'))
        b, _ = fs.run_h1(h1, 'EURUSD', fs.config('naive:p=0.05:seed=1'))
        c, _ = fs.run_h1(h1, 'EURUSD', fs.config('naive:p=0.05:seed=2'))
        self.assertEqual([t['entry_time'] for t in a], [t['entry_time'] for t in b])
        self.assertNotEqual([t['entry_time'] for t in a], [t['entry_time'] for t in c])
        self.assertGreater(len(a), 10)
        atr = fd_atr(h1)
        pos = {t: i for i, t in enumerate(h1.index)}
        for t in a:
            i = pos[t['entry_time']]
            self.assertAlmostEqual(abs(t['entry'] - t['initial_sl']), 1.5 * atr[i - 1], places=9)


def fd_atr(h1):
    from fusion import indicators as ind
    return ind.atr(h1['High'].to_numpy(), h1['Low'].to_numpy(), h1['Close'].to_numpy(), 14)


if __name__ == '__main__':
    unittest.main()
