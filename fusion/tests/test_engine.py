"""エンジンの基本動作テスト"""
import unittest

import numpy as np
import pandas as pd

from fusion import engine as eg


def make_h1(days=10, start='2020-01-06', step=0.0001):
    idx = pd.date_range(start, periods=24 * days, freq='1h')
    idx = idx[idx.dayofweek < 5]
    c = 1.1 + np.arange(len(idx)) * step
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({'Open': o, 'High': np.maximum(o, c) + 0.0002, 'Low': np.minimum(o, c) - 0.0002,
                         'Close': c, 'Volume': 1.0}, index=idx)


class Dummy:
    def __init__(self, hold=3):
        self.hold = hold
        self.calls = []

    def prepare(self, engine):
        self.engine = engine

    def on_bar_close(self, ctx):
        self.calls.append((ctx.time, ctx.last['H4'], ctx.closed_now['H4']))
        if ctx.time.dayofweek == 0 and ctx.time.hour == 10:
            c = self.engine.C[ctx.i]
            return [eg.Order(direction=1, sl=c - 0.0050, tp_r=10.0, meta={'tag': 'mon10'})]
        return []

    def manage(self, ctx, pos):
        if pos.bars_held >= self.hold:
            ctx.close(pos, 'TIME')


class TestEngine(unittest.TestCase):
    def test_fill_next_open_and_time_exit(self):
        h1 = make_h1()
        e = eg.Engine({'H1': h1}, Dummy(hold=3), spread=0.0)
        trades = e.run()
        self.assertEqual(len(trades), 2)                       # 2回の月曜
        t0 = trades[0]
        self.assertEqual(t0['entry_time'], pd.Timestamp('2020-01-06 11:00'))   # 10時足の次の足
        self.assertAlmostEqual(t0['entry'], h1.loc['2020-01-06 11:00', 'Open'])
        self.assertEqual(t0['exit_reason'], 'TIME')

    def test_h4_mapping_in_context(self):
        h1 = make_h1(days=3)
        d = Dummy()
        eg.Engine({'H1': h1}, d).run()
        calls = {t: (j, now) for t, j, now in d.calls}
        # 03:00 の1H足の確定（04:00）で 00:00 の4H足（index 0）が確定
        self.assertEqual(calls[pd.Timestamp('2020-01-06 03:00')], (0, True))
        self.assertEqual(calls[pd.Timestamp('2020-01-06 04:00')], (0, False))
        self.assertEqual(calls[pd.Timestamp('2020-01-06 02:00')][0], -1)

    def test_weekend_close(self):
        h1 = make_h1(days=12)
        class HoldForever(Dummy):
            def on_bar_close(self, ctx):
                if ctx.time == pd.Timestamp('2020-01-09 10:00'):   # 木曜
                    c = self.engine.C[ctx.i]
                    return [eg.Order(direction=1, sl=c - 0.05)]
                return []
            def manage(self, ctx, pos):
                pass
        trades = eg.Engine({'H1': h1}, HoldForever(), friday_close_hour=22).run()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]['exit_reason'], 'WEEKEND')
        self.assertEqual(trades[0]['exit_time'], pd.Timestamp('2020-01-10 22:00'))

    def test_stop_entry(self):
        h1 = make_h1(days=3)
        class StopBuy(Dummy):
            def on_bar_close(self, ctx):
                if ctx.time == pd.Timestamp('2020-01-06 05:00'):
                    c = self.engine.C[ctx.i]
                    return [eg.Order(direction=1, sl=c - 0.01, entry='stop', stop_price=c + 0.0003, expiry_bars=5)]
                return []
            def manage(self, ctx, pos):
                if pos.bars_held >= 2:
                    ctx.close(pos, 'TIME')
        tr = eg.Engine({'H1': h1}, StopBuy()).run()
        self.assertEqual(len(tr), 1)
        c5 = h1.loc['2020-01-06 05:00', 'Close']
        self.assertAlmostEqual(tr[0]['entry'], c5 + 0.0003)


if __name__ == '__main__':
    unittest.main()
