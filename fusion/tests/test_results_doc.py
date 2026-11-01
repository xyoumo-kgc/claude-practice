"""最終検証の結果の文書（fusion/RESULTS.md）が、コミットした出力と食い違っていないかを確かめる。

fusion/results/final_eval_trades_main.csv.gz は、最終評価（python -m fusion.final_eval、コミット 29605d2）が出した
trades.csv.gz から、主要6構成の未接触プール（U-A・U-B・U-C）の取引だけを抜き出したもの。
全181構成の取引一覧は約55MB あるのでコミットしていない（同じコマンドで作り直せる）。
"""
import json
import os
import re
import unittest

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(ROOT, 'fusion', 'results')
TRADES = os.path.join(RESULTS, 'final_eval_trades_main.csv.gz')
MAIN = ['fusion', 'oku_only', 'kenjin_only', 'mincore_final', 'ma_slope', 'fourp_score']

# RESULTS.md「当初の検証期間」の表（README 規則1の 2018-01〜2020-05 を U-B から4銘柄だけ切り出したもの）
INITIAL_SYMBOLS = ['EURUSD', 'GBPUSD', 'EURJPY', 'XAUUSD']
INITIAL_ROWS = {  # 構成: (回数, 総R, 平均R, PF)
    'fusion': (276, 11.1, 0.040, 1.06),
    'oku_only': (36, -2.9, -0.080, 0.82),
    'kenjin_only': (61, -10.5, -0.171, 0.78),
    'ma_slope': (870, -66.9, -0.077, 0.89),
    'fourp_score': (99, -16.8, -0.170, 0.76),
}


def _pf(r):
    loss = -r[r < 0].sum()
    return r[r > 0].sum() / loss if loss > 0 else float('inf')


class TestResultsDoc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(TRADES)
        with open(os.path.join(RESULTS, 'final_eval_results.json'), encoding='utf-8') as f:
            cls.js = json.load(f)
        with open(os.path.join(ROOT, 'fusion', 'RESULTS.md'), encoding='utf-8') as f:
            cls.md = f.read()

    def test_trades_match_results_json(self):
        """抜き出した取引一覧の回数・総R・プール別の回数が、results.json の集計と一致する"""
        self.assertEqual(sorted(self.df['config'].unique()), sorted(MAIN))
        for c in MAIN:
            d = self.df[self.df['config'] == c]
            agg = self.js['configs'][c]['合算']
            self.assertEqual(len(d), agg['trades'], c)
            self.assertAlmostEqual(d['pnl_r'].sum(), agg['total_r'], places=3, msg=c)
            for pool, st in self.js['configs'][c]['プール別'].items():
                self.assertEqual(int((d['pool'] == pool).sum()), st['trades'], (c, pool))

    def test_initial_period_table(self):
        """「当初の検証期間」の表は、同じ実行の U-B から4銘柄を切り出すと再現できる"""
        for c, (n, total, avg, pf) in INITIAL_ROWS.items():
            d = self.df[(self.df['config'] == c) & (self.df['pool'] == 'U-B')
                        & self.df['symbol'].isin(INITIAL_SYMBOLS)]
            r = d['pnl_r']
            self.assertEqual(len(d), n, c)
            self.assertAlmostEqual(round(r.sum(), 1), total, places=6, msg=c)
            self.assertAlmostEqual(round(r.mean(), 3), avg, places=6, msg=c)
            self.assertAlmostEqual(round(_pf(r), 2), pf, places=6, msg=c)

    def test_results_md_headline(self):
        """RESULTS.md の結論の数値（回数・平均R・t・95%区間）が results.json と一致する"""
        agg = self.js['configs']['fusion']['合算']
        self.assertIn(f"{agg['trades']:,}回", self.md)
        self.assertIn(f"+{agg['avg_r']:.3f}R", self.md)
        self.assertIn(f"t は{agg['t_stat']:.2f}", self.md)
        lo, hi = agg['ci95_lo'], agg['ci95_hi']
        self.assertIn(f"−{abs(lo):.3f}〜+{hi:.3f}R", self.md)
        self.assertIn(f"最大連敗", self.md)
        streak = agg['max_losing_streak']
        self.assertTrue(re.search(rf"\|\s*{streak}\s*\|", self.md), '成績表の最大連敗')

    def test_results_md_initial_table(self):
        """RESULTS.md の「当初の検証期間」の表の値が、上の再現値と同じ"""
        sec = self.md[self.md.index('### 当初の検証期間'):]
        sec = sec[:sec.index('\n## ')]
        for c, (n, total, avg, pf) in INITIAL_ROWS.items():
            sign = '+' if total > 0 else '−'
            self.assertIn(f"| {n} | {sign}{abs(total):.1f} |", sec, c)


if __name__ == '__main__':
    unittest.main()
