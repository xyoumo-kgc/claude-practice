"""基盤（データ・インジケーター・約定）のテスト:  python -m unittest discover -s fusion/tests -t ."""
import os
import unittest

import numpy as np
import pandas as pd

from fusion import broker as bk
from fusion import data as fd
from fusion import indicators as ind


def random_ohlc(n=600, seed=1):
    rng = np.random.default_rng(seed)
    c = 1.1 + np.cumsum(rng.normal(0, 0.001, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 0.0008, n)
    l = np.minimum(o, c) - rng.uniform(0, 0.0008, n)
    # 同値の高値・安値をわざと混ぜる（不等号の境界テスト）
    h[100] = h[101] = h[102] = max(h[100:103])
    return h, l, c


def mql5_scan(high, low, last_closed, depth, lookback, want_high, k=4):
    """MQL5 FindSwingHighs/Lows をそのまま写した総当たり版（series 添字で走査）"""
    cur = last_closed + 1
    ibars = cur + 1
    bars = min(lookback, ibars - depth - 1)
    out = []
    for i in range(depth + 1, bars):
        j = cur - i
        if j - depth < 0:
            break
        ok = True
        for kk in range(1, depth + 1):
            if want_high:
                if high[j] <= high[j + kk] or high[j] < high[j - kk]:
                    ok = False
            else:
                if low[j] >= low[j + kk] or low[j] > low[j - kk]:
                    ok = False
        if ok:
            out.append((float((high if want_high else low)[j]), j))
            if len(out) >= k:
                break
    return out


class TestIndicators(unittest.TestCase):
    def test_swingbook_matches_mql5_scan(self):
        h, l, _ = random_ohlc()
        for depth in (2, 3, 5):
            book = ind.SwingBook(h, l, depth, lookback=120)
            for last in range(30, len(h) - 1, 7):
                self.assertEqual(book.highs(last, 4), mql5_scan(h, l, last, depth, 120, True))
                self.assertEqual(book.lows(last, 4), mql5_scan(h, l, last, depth, 120, False))

    def test_no_lookahead_on_truncation(self):
        h, l, c = random_ohlc(800, seed=7)
        full_atr, full_sma = ind.atr(h, l, c, 14), ind.sma(c, 20)
        book_full = ind.SwingBook(h, l, 3, lookback=400)
        for cut in (100, 333, 500, 799):
            hh, ll, cc = h[:cut + 1], l[:cut + 1], c[:cut + 1]
            np.testing.assert_allclose(ind.atr(hh, ll, cc, 14), full_atr[:cut + 1], equal_nan=True)
            np.testing.assert_allclose(ind.sma(cc, 20), full_sma[:cut + 1], equal_nan=True)
            book_cut = ind.SwingBook(hh, ll, 3, lookback=400)
            self.assertEqual(book_cut.highs(cut, 6), book_full.highs(cut, 6))
            self.assertEqual(book_cut.lows(cut, 6), book_full.lows(cut, 6))
            self.assertEqual(book_cut.dow_trend(cut), book_full.dow_trend(cut))

    def test_closed_index_map(self):
        idx = pd.date_range('2020-01-06', periods=24 * 10, freq='1h')
        idx = idx[idx.dayofweek < 5]
        h1 = pd.DataFrame({'Open': 1.0, 'High': 1.0, 'Low': 1.0, 'Close': 1.0, 'Volume': 1.0}, index=idx)
        h4 = fd.resample(h1, 'H4')
        d1 = fd.resample(h1, 'D1')
        m4 = ind.closed_index_map(h1.index, fd.TF_DELTA['H1'], h4.index, fd.TF_DELTA['H4'])
        md = ind.closed_index_map(h1.index, fd.TF_DELTA['H1'], d1.index, fd.TF_DELTA['D1'])
        for i, t in enumerate(h1.index):
            close = t + pd.Timedelta(hours=1)
            if m4[i] >= 0:
                self.assertLessEqual(h4.index[m4[i]] + pd.Timedelta(hours=4), close)
            if m4[i] + 1 < len(h4):
                self.assertGreater(h4.index[m4[i] + 1] + pd.Timedelta(hours=4), close)
            if md[i] >= 0:
                self.assertLessEqual(d1.index[md[i]] + pd.Timedelta(days=1), close)
        # 03:00の1H足（04:00確定）で 00:00 の4H足が確定済みになる
        t = pd.Timestamp('2020-01-07 03:00')
        self.assertEqual(h4.index[m4[h1.index.get_loc(t)]], pd.Timestamp('2020-01-07 00:00'))
        t = pd.Timestamp('2020-01-07 02:00')
        self.assertEqual(h4.index[m4[h1.index.get_loc(t)]], pd.Timestamp('2020-01-06 20:00'))


class TestBroker(unittest.TestCase):
    def test_sl_priority_same_bar(self):
        b = bk.Broker(spread=0.0)
        p = b.open_position('t0', 1.1000, 1, sl=1.0950, tp=1.1100)
        b.process_bar(p, 't1', 1.1000, 1.1120, 1.0940, 1.1050)
        self.assertEqual(len(b.closed), 1)
        self.assertAlmostEqual(b.closed[0].realized_r, -1.0)

    def test_tp_and_spread(self):
        b = bk.Broker(spread=0.0002)
        p = b.open_position('t0', 1.1000, 1, sl=1.0950, tp=1.1100)
        self.assertAlmostEqual(p.entry_price, 1.1001)
        b.process_bar(p, 't1', 1.1000, 1.11005, 1.0990, 1.1090)  # Bid高値 1.10995 < TP
        self.assertEqual(len(b.open), 1)
        b.process_bar(p, 't2', 1.1090, 1.1102, 1.1080, 1.1095)   # Bid高値 1.1101 >= TP
        self.assertEqual(len(b.closed), 1)
        self.assertAlmostEqual(p.realized_r, (1.1100 - 1.1001) / (1.1001 - 1.0950))

    def test_gap_through_sl(self):
        b = bk.Broker()
        p = b.open_position('t0', 1.2000, -1, sl=1.2050)
        b.process_bar(p, 't1', 1.2080, 1.2090, 1.2070, 1.2075)   # 売りの損切りを越えて窓開け
        self.assertAlmostEqual(p.realized_r, -(1.2080 - 1.2000) / 0.0050)
        self.assertEqual(p.exits[-1][3], 'SL_gap')

    def test_partial_then_be_same_bar(self):
        b = bk.Broker()
        p = b.open_position('t0', 1.0, 1, sl=0.99, tp=1.03, tp1=1.01, tp1_frac=0.5, be_after_tp1=True)
        b.process_bar(p, 't1', 1.0, 1.012, 0.9995, 1.005)   # TP1到達、安値は建値を下回る → 残りは建値
        self.assertEqual(len(b.closed), 1)
        self.assertAlmostEqual(p.realized_r, 0.5)
        self.assertEqual([e[3] for e in p.exits], ['TP1', 'BE'])

    def test_trailing_only_tightens(self):
        b = bk.Broker()
        p = b.open_position('t0', 1.0, 1, sl=0.99)
        self.assertFalse(b.modify_sl(p, 0.98))
        self.assertTrue(b.modify_sl(p, 0.995))
        b.process_bar(p, 't1', 1.0, 1.001, 0.994, 0.996)
        self.assertEqual(p.exits[-1][3], 'TRAIL')
        self.assertAlmostEqual(p.realized_r, -0.5)


class TestData(unittest.TestCase):
    def test_backtesting_eurusd_server_time(self):
        try:
            df = fd.load_backtesting_eurusd()
        except FileNotFoundError:
            self.skipTest('backtesting 未インストール')
        self.assertTrue((df.index.dayofweek < 5).all())
        d1 = fd.resample(df, 'D1')
        self.assertLessEqual(d1.index.dayofweek.max(), 4)
        h4 = fd.resample(df, 'H4')
        self.assertTrue(set(h4.index.hour) <= {0, 4, 8, 12, 16, 20})
        self.assertEqual(fd.infer_tf(df), 'H1')

    def test_mt5_csv(self):
        import tempfile
        txt = ('<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n'
               '2024.01.02\t00:00:00\t2063.10\t2065.00\t2060.00\t2064.00\t1000\t0\t20\n'
               '2024.01.02\t01:00:00\t2064.00\t2066.00\t2062.00\t2065.50\t900\t0\t20\n')
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as f:
            f.write(txt)
            path = f.name
        try:
            df = fd.load_mt5_csv(path)
            self.assertEqual(len(df), 2)
            self.assertEqual(df.index[1], pd.Timestamp('2024-01-02 01:00'))
            self.assertAlmostEqual(df['Close'].iloc[1], 2065.5)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()


class TestFeatures(unittest.TestCase):
    def test_cluster_and_next_level(self):
        from fusion import features as ft
        sw = [(1.1000, 10, 1), (1.1004, 30, -1), (1.0950, 20, -1), (1.1100, 40, 1), (1.1102, 50, 1)]
        lv = ft.cluster_levels(sw, tol=0.0005)
        self.assertEqual(len(lv), 3)
        mid = next(l for l in lv if abs(l.price - 1.1002) < 1e-9)
        self.assertTrue(mid.role_reversal)
        self.assertEqual(mid.touches, 2)
        up = ft.next_level(lv, 1.1010, +1)
        self.assertAlmostEqual(up.price, 1.1101)
        dn = ft.next_level(lv, 1.1010, -1)
        self.assertAlmostEqual(dn.price, 1.1002)
        self.assertIsNone(ft.next_level(lv, 1.1200, +1))
        sup = ft.support_near(lv, 1.1006, +1, tol=0.0005)
        self.assertAlmostEqual(sup.price, 1.1002)

    def test_converge_then_diverge(self):
        from fusion import features as ft
        gap = np.array([2.0, 1.0, 0.2, 0.1, 0.4, 0.9, 1.3])
        self.assertTrue(ft.converge_then_diverge(gap, 6, +1, conv_thr=0.3, div_thr=1.0, window=5))
        self.assertFalse(ft.converge_then_diverge(gap, 6, -1, conv_thr=0.3, div_thr=1.0, window=5))
        self.assertFalse(ft.converge_then_diverge(gap, 1, +1, conv_thr=0.3, div_thr=1.0, window=5))
        self.assertAlmostEqual(ft.risk_reward(1.0, 0.99, 1.03, +1), 3.0)
