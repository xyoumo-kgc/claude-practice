"""snapshot()（ダッシュボード・分析スキル用の状態取得）のテスト"""
import unittest

from fusion import strategy as fs
from fusion.tests.test_strategy import trending_h1


class TestSnapshot(unittest.TestCase):
    def test_trace_does_not_change_trades(self):
        h1 = trending_h1()
        for variant in ('fusion', 'oku_only', 'F+p3'):
            a, fa = fs.run_h1(h1, 'EURUSD', fs.config(variant))
            b, fb = fs.run_h1(h1, 'EURUSD', fs.config(variant), trace=lambda *x: None)
            self.assertEqual(a, b, variant)
            self.assertEqual(fa, fb, variant)

    def test_snapshot_matches_run(self):
        h1 = trending_h1()
        seen = set()
        full_trades, _ = fs.run_h1(h1, 'EURUSD')
        pos = {t: i for i, t in enumerate(h1.index)}
        entry_cuts = [pos[t['entry_time']] for t in full_trades][::3]     # 約定足の直前で切る＝逆指値が置かれている
        for cut in sorted(set(entry_cuts + list(range(1500, len(h1), 400)) + [e + 3 for e in entry_cuts])):
            part = h1.iloc[:cut]
            snap = fs.snapshot(part, 'EURUSD')
            trades, _ = fs.run_h1(part, 'EURUSD')
            done = [t for t in trades if t['exit_reason'] != 'END']
            self.assertEqual(len(snap['trades']), len(done))
            self.assertEqual(snap['time'], part.index[-1])
            open_end = [t for t in trades if t['exit_reason'] == 'END']
            self.assertEqual(snap['position'] is not None, bool(open_end))
            if snap['position']:
                self.assertEqual(snap['position']['entry_time'], open_end[0]['entry_time'])
                seen.add('FILLED')
                self.assertEqual(snap['evals'], {})          # 建玉があるときは新規判定をしない
            for d, e in snap['evals'].items():
                self.assertIn(e['state'], ('IDLE', 'WATCH', 'ZONE', 'ARMED'))
                seen.add(e['state'])
                if e['state'] == 'ARMED':
                    self.assertIsNotNone(snap['pending'])
                    self.assertIn('price', e['diag'])
            if snap['pending']:
                p = snap['pending']
                self.assertGreater((p['price'] - p['sl']) * p['dir'], 0)
                # 次の足でこの逆指値に届けば、その価格で約定する
                nxt = h1.iloc[cut] if cut < len(h1) else None
                if nxt is not None:
                    full, _ = fs.run_h1(h1.iloc[:cut + 1], 'EURUSD')
                    hit = (nxt['High'] + fs.S_NOM['EURUSD'] / 2 >= p['price']) if p['dir'] == 1 else \
                          (nxt['Low'] - fs.S_NOM['EURUSD'] / 2 <= p['price'])
                    entered = [t for t in full if t['entry_time'] == h1.index[cut]]
                    self.assertEqual(bool(entered), bool(hit))
        self.assertTrue({'IDLE', 'ARMED', 'FILLED'} <= seen, seen)


if __name__ == '__main__':
    unittest.main()
