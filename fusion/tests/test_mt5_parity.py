"""fusion/mt5_parity.py（MT5 EA のログと Python 参照実装の照合ハーネス）のテスト

  python3 -m unittest fusion.tests.test_mt5_parity

合成データで Python の結果を EA のログ形式（<銘柄>_trades.csv・_eval.csv・_bars.csv・_info.csv）に書き出し、
  1) 自分自身と比べると全一致になる（取引・評価ログ・CLI の終了コード）
  2) わざと1件ずらす・消す・SL を動かす・理由コードを変えると、最初の食い違いとして検出し、SPEC §17 のヒントを出す
  3) サーバー時間のずれ（--offset）、始点の推定、実約定のログ、表にない銘柄、追加の暦を扱える
ことを確かめる。環境変数 FUSION_DATA_DIR に EURUSD_H1.csv（開発期間 2013〜2017 のデータ）があれば、
2013 年の EURUSD でも自分自身との全一致を確かめる（それ以外の期間は読まない）。
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

from fusion import data as fd
from fusion import mt5_parity as mp
from fusion import strategy as fs
from fusion.tests.test_strategy import trending_h1

HOUR = pd.Timedelta(hours=1)
OHLC = ['Open', 'High', 'Low', 'Close']


def holiday_h1(n=6000):
    """年末年始（12/24・12/25・12/31・1/1）を含む合成 H1（trending_h1 を35週ずらしたもの。価格は MT5 と同じく5桁）"""
    h = trending_h1(n=n)
    h.index = h.index + pd.Timedelta(weeks=35)
    return h.round(5)


def gapped_h1(n=6000):
    """休場明け（隔週水曜の13時間の穴＋窓開け）と、ふつうの足の窓開け（火曜10時）を入れた合成 H1。
    GAP_FALLBACK と SL_gap の決済が起きる"""
    h = trending_h1(n=n)
    h.index = h.index + pd.Timedelta(weeks=35)
    wk = (h.index - h.index[0]).days // 7
    hole = (h.index.dayofweek == 2) & (h.index.hour >= 3) & (h.index.hour < 16) & (wk % 2 == 0)
    h = h[~hole].copy()
    wk = (h.index - h.index[0]).days // 7
    reopen = (h.index.dayofweek == 2) & (h.index.hour == 16) & (wk % 2 == 0)
    tue = (h.index.dayofweek == 1) & (h.index.hour == 10)
    shift = np.zeros(len(h))
    sign = 1.0
    for i in np.flatnonzero(reopen | tue):
        shift[i:] += sign * (0.0025 if reopen[i] else 0.004)
        sign = -sign
    for c in OHLC:
        h[c] = h[c] + shift
    return h.round(5)


def run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = mp.main(argv)
    return code, out.getvalue()


def write_trades(df, path, real=False):
    """EA の取引ログ形式で書く（real=True なら _real.csv と同じく ticket 列をつける）"""
    with open(path, 'w', encoding='utf-8', newline='') as f:
        if real:
            f.write('entry_time,dir,entry,initial_sl,exit_time,exit_reason,R,key_time,score,ticket\r\n')
            for i, r in enumerate(df.to_dict('records')):
                f.write(','.join([r['entry_time'].strftime(mp.TIME_FMT), str(int(r['dir'])), f"{r['entry']:.8f}",
                                  f"{r['initial_sl']:.8f}", r['exit_time'].strftime(mp.TIME_FMT), r['exit_reason'],
                                  f"{r['R']:.6f}", r['key_time'].strftime(mp.TIME_FMT), str(int(r['score'])), str(1000 + i)]) + '\r\n')
        else:
            f.write(mp.TRADE_HEADER + '\r\n')
            for r in df.to_dict('records'):
                f.write(mp.trade_csv_line(r) + '\r\n')


def write_eval(df, path):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(mp.EVAL_HEADER + '\r\n')
        for r in df.to_dict('records'):
            f.write(mp.eval_csv_line(r) + '\r\n')


def write_bars(df, path):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('Time,Open,High,Low,Close\r\n')
        for ts, r in zip(df.index, df[OHLC].to_numpy(float)):
            f.write(f'{ts.strftime(mp.TIME_FMT)},' + ','.join(f'{x:.10f}' for x in r) + '\r\n')


class SelfParity(unittest.TestCase):
    """Python の結果を EA の形式に書き出し、自分自身と比べる"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='mt5_parity_')
        cls.bars = holiday_h1()
        cls.py = mp.run_python(cls.bars, 'EURUSD')
        cls.paths = mp.write_python_logs(cls.py, cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ea_frames(self):
        tr, real = mp.read_trades(self.paths['trades'])
        self.assertFalse(real)
        return tr, mp.read_eval(self.paths['eval'])

    def compare(self, tr, ev=None, **kw):
        return mp.compare_logs(self.py, tr, ev, **kw)

    def trade_k(self):
        """1本先も平日の続きの足（週末や休場をまたがない）取引"""
        idx = self.py.bars.index
        for k, te in enumerate(self.py.trades['entry_bar']):
            if k >= 3 and te + 2 < len(idx) and idx[te + 2] - idx[te] == 2 * HOUR:
                return k, int(te)
        self.fail('ずらせる取引がない')

    # ---------------------------------------------------------------- 書き出しの形式
    def test_export_is_ea_format(self):
        with open(self.paths['eval'], encoding='utf-8', newline='') as f:     # EA と同じく CRLF
            lines = [x for x in f.read().split('\r\n') if x]
        self.assertEqual(lines[0], mp.EVAL_HEADER)
        body = lines[1:]
        self.assertTrue(all(len(x.split(',')) == len(mp.EVAL_COLS) for x in body))
        self.assertRegex(body[0], r'^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2},')
        codes = Counter(x.split(',')[4] for x in body)
        for k, v in self.py.funnel.items():                    # R コードと ARMED の件数は run_h1 の funnel と同じ
            self.assertEqual(codes[k], v, k)
        for c in ('T1', 'T2', 'T3', 'T4', 'T5', 'UPDATE', 'ARMED', 'R01', 'R02', 'R04', 'R10'):
            self.assertIn(c, codes)
        self.assertEqual({str(d) for d in self.py.evals.loc[self.py.evals['code'] == 'T1', 'bar_time'].dt.date},
                         {'2015-12-25', '2016-01-01'})          # 休場日（SPEC §2.6）
        with open(self.paths['trades'], encoding='utf-8', newline='') as f:
            tl = [x for x in f.read().split('\r\n') if x]
        self.assertEqual(tl[0], mp.TRADE_HEADER)
        self.assertEqual(len(tl) - 1, len(self.py.trades))
        bars = fd.load_mt5_csv(self.paths['bars'])              # _bars.csv は fusion.data.load_mt5_csv で読める
        self.assertTrue((bars.index == self.bars.index).all())
        np.testing.assert_array_equal(bars[OHLC].to_numpy(), self.bars[OHLC].to_numpy())
        info = mp.read_info(self.paths['info'])
        self.assertEqual(info['first_bar_time'], self.bars.index[0].strftime(mp.TIME_FMT))
        self.assertEqual(info['first_eval_time'], self.bars.index[92].strftime(mp.TIME_FMT))
        self.assertEqual(mp.switches_from_info(info), {})

    def test_round_trip_values(self):
        tr, ev = self.ea_frames()
        self.assertEqual(len(ev), len(self.py.evals))
        cand = ev[ev['code'].isin(mp.CANDIDATE)]
        self.assertGreater(len(cand), 50)
        self.assertTrue(cand[['price', 'sl', 'R', 'r_atr', 'tp1', 'score', 'S1', 'S6']].notna().all().all())
        r10 = ev[ev['code'] == 'R10']
        self.assertTrue(r10['r_atr'].gt(3.0).all())             # R10 の行には R/ATR が入る（stage 3）
        self.assertTrue(r10['score'].isna().all())
        t_rows = ev[ev['code'].isin(mp.T_CODES)]
        self.assertTrue((t_rows['dir'] == 0).all() and t_rows['key_time'].isna().all())

    # ---------------------------------------------------------------- 自分自身と比べる
    def test_self_comparison_is_exact(self):
        tr, ev = self.ea_frames()
        res = self.compare(tr, ev)
        tc, ec = res.tcmp, res.ecmp
        n = len(self.py.trades)
        self.assertGreaterEqual(n, 20)
        self.assertTrue(res.passed)
        self.assertTrue(res.exact)
        self.assertEqual((tc.n_ea, tc.n_py, len(tc.pairs)), (n, n, n))
        self.assertEqual(tc.count_diff, 0.0)
        self.assertEqual(tc.dir_rate, 1.0)
        self.assertLess(tc.sl_max_pts, 1e-3)
        self.assertEqual(tc.exit_rate, 1.0)
        self.assertEqual(tc.mismatches, [])
        self.assertEqual(ec.rate, 1.0)
        self.assertEqual((ec.only_ea, ec.only_py), (0, 0))
        self.assertFalse(ec.field_mismatch)
        self.assertIsNone(ec.first_code)
        self.assertIn('食い違い: なし', mp.format_report(res))

    def test_cli_self_comparison(self):
        js = os.path.join(self.tmp, 'self.json')
        code, out = run_cli(['--bars', self.paths['bars'], '--trades', self.paths['trades'], '--eval', self.paths['eval'],
                             '--symbol', 'EURUSD', '--strict', '--json', js])
        self.assertEqual(code, 0, out)
        self.assertIn('判定: 合格', out)
        self.assertIn('食い違い: なし', out)
        self.assertIn('first_bar_time', out.replace('EA の first_bar_time', 'first_bar_time'))
        with open(js, encoding='utf-8') as f:
            r = json.load(f)
        self.assertTrue(r['passed'])
        self.assertTrue(r['exact'])
        self.assertEqual(r['eval']['code_match_rate'], 1.0)

    # ---------------------------------------------------------------- わざとずらすと検出する
    def test_one_bar_shift_is_detected(self):
        tr, ev = self.ea_frames()
        k, te = self.trade_k()
        tr.loc[k, 'entry_time'] = self.py.bars.index[te + 1]
        res = self.compare(tr, ev)
        tc = res.tcmp
        self.assertTrue(res.passed)                             # ±1本以内なので SPEC §18 の基準は満たす
        self.assertFalse(tc.exact)                              # が、完全一致ではない
        self.assertEqual(dict(tc.issue_count), {'SHIFT': 1})
        self.assertEqual(len(tc.mismatches), 1)
        m = tc.mismatches[0]
        self.assertEqual(m['kind'], 'SHIFT')
        self.assertEqual(m['time'], self.py.trades.at[k, 'entry_time'])
        lines, hints = mp.first_trade_detail(res)
        self.assertIn('エントリーが1本ずれた', lines[0])
        self.assertTrue(hints)

    def test_two_bar_shift_breaks_the_pair(self):
        tr, ev = self.ea_frames()
        k, te = self.trade_k()
        tr.loc[k, 'entry_time'] = self.py.bars.index[te + 2]
        tc = self.compare(tr, ev).tcmp
        n = len(self.py.trades)
        self.assertEqual(dict(tc.issue_count), {'EA_ONLY': 1, 'PY_ONLY': 1})
        self.assertAlmostEqual(tc.dir_rate, (n - 1) / n)
        self.assertEqual(tc.mismatches[0]['kind'], 'PY_ONLY')
        self.assertEqual(tc.mismatches[0]['time'], self.py.trades.at[k, 'entry_time'])

    def test_dropped_trade_is_detected(self):
        tr, ev = self.ea_frames()
        k, _ = self.trade_k()
        tr = tr.drop(index=k).reset_index(drop=True)
        res = self.compare(tr, ev)
        tc = res.tcmp
        n = len(self.py.trades)
        self.assertEqual((tc.n_ea, tc.n_py), (n - 1, n))
        self.assertAlmostEqual(tc.count_diff, -1 / n)
        self.assertEqual(dict(tc.issue_count), {'PY_ONLY': 1})
        self.assertEqual(tc.mismatches[0]['time'], self.py.trades.at[k, 'entry_time'])
        _, hints = mp.first_trade_detail(res)
        self.assertTrue({h['tag'] for h in hints} & {'spread', 'engine'})   # 直前の足は両側で同じ → 約定判定

    def test_initial_sl_tolerance_is_one_point(self):
        tr, ev = self.ea_frames()
        k, _ = self.trade_k()
        far = tr.copy()
        far.loc[k, 'initial_sl'] += 3e-5                        # 3ポイント
        res = self.compare(far, ev)
        self.assertFalse(res.tcmp.sl_ok)
        self.assertFalse(res.passed)
        self.assertEqual(res.tcmp.sl_over, 1)
        self.assertAlmostEqual(res.tcmp.sl_max_pts, 3.0, places=3)
        self.assertEqual(res.tcmp.mismatches[0]['kind'], 'SL')
        near = tr.copy()
        near.loc[k, 'initial_sl'] += 0.5e-5                     # 0.5ポイント: 基準内だが完全一致ではない
        res = self.compare(near, ev)
        self.assertTrue(res.tcmp.sl_ok)
        self.assertTrue(res.passed)
        self.assertFalse(res.tcmp.exact)
        self.assertEqual(dict(res.tcmp.issue_count), {'SL_EXACT': 1})

    def test_exit_reason_mismatch_is_reported(self):
        tr, ev = self.ea_frames()
        k = int(np.flatnonzero(tr['exit_reason'] == 'WEEKEND')[0])
        tr.loc[k, 'exit_reason'] = 'SL'
        res = self.compare(tr, ev)
        self.assertTrue(res.passed)                             # 決済理由は参考（合格基準ではない）
        self.assertEqual(res.tcmp.exit_match, len(self.py.trades) - 1)
        self.assertIn('EXIT_REASON', res.tcmp.mismatches[0]['issues'])
        _, hints = mp.first_trade_detail(res)
        self.assertIn('time_rules', {h['tag'] for h in hints})  # WEEKEND が絡む → 時刻ルール

    def test_eval_code_change_is_detected(self):
        tr, ev = self.ea_frames()
        i = int(np.flatnonzero(ev['code'] == 'ARMED')[3])
        ev.loc[i, 'code'] = 'R10'
        res = self.compare(tr, ev)
        ec = res.ecmp
        self.assertEqual(ec.n_match, ec.n_union - 1)
        self.assertEqual(dict(ec.confusion), {('R10', 'ARMED'): 1})
        self.assertEqual(ec.first_code['bar_time'], ev.at[i, 'bar_time'])
        self.assertFalse(res.exact)
        self.assertTrue(res.passed)                             # 取引は同じ
        lines, hints = mp.first_eval_detail(res)
        self.assertIn('評価ログの最初の食い違い', lines[0])
        self.assertEqual(hints[0]['tag'], 'engine')            # 両側の R/ATR は同じで閾値から遠い → 判定式の移植
        self.assertIn('R10→ARMED 1', mp.format_report(res))

    def test_boundary_value_hint(self):
        tr, ev = self.ea_frames()
        i = int(np.flatnonzero(ev['code'] == 'ARMED')[3])
        ev.loc[i, 'code'] = 'R10'
        ev.loc[i, 'r_atr'] = 3.0                                # EA 側の R/ATR が上限ちょうど
        _, hints = mp.first_eval_detail(self.compare(tr, ev))
        self.assertEqual(hints[0]['tag'], 'rounding')

    def test_time_code_change_hint(self):
        tr, ev = self.ea_frames()
        i = int(np.flatnonzero(ev['code'] == 'T2')[0])
        ev.loc[i, 'code'] = 'T3'
        _, hints = mp.first_eval_detail(self.compare(tr, ev))
        self.assertEqual(hints[0]['tag'], 'time_rules')

    def test_from_to_window(self):
        tr, ev = self.ea_frames()
        k, te = self.trade_k()
        tr.loc[k, 'entry_time'] = self.py.bars.index[te + 2]   # この取引の食い違いを
        cut = self.py.trades.at[k, 'exit_time'] + HOUR          # 期間の外に出す
        res = self.compare(tr, ev, t_from=cut)
        self.assertTrue(res.tcmp.exact)
        self.assertEqual(res.tcmp.n_py, int((self.py.trades['entry_time'] >= cut).sum()))
        self.assertEqual(res.ecmp.n_union, int((self.py.evals['bar_time'] >= cut).sum()))

    def test_cli_exit_codes_for_corrupted_logs(self):
        d = tempfile.mkdtemp(dir=self.tmp)
        for k in ('bars', 'info', 'eval'):
            shutil.copy(self.paths[k], d)
        tr, _ = self.ea_frames()
        k, te = self.trade_k()
        shifted = tr.copy()
        shifted.loc[k, 'entry_time'] = self.py.bars.index[te + 1]
        tpath = os.path.join(d, 'EURUSD_trades.csv')
        write_trades(shifted, tpath)
        args = ['--bars', os.path.join(d, 'EURUSD_bars.csv'), '--trades', tpath, '--eval', os.path.join(d, 'EURUSD_eval.csv'),
                '--symbol', 'EURUSD']
        code, out = run_cli(args)
        self.assertEqual(code, 0, out)                          # §18 の基準は満たす
        self.assertIn('エントリーが1本ずれた', out)
        self.assertIn('完全一致（約定・決済の時刻と価格、理由、R、保有本数、key、スコア）: いいえ', out)
        code, _ = run_cli(args + ['--strict'])
        self.assertEqual(code, 1)                               # --strict では完全一致が必要
        far = tr.copy()
        far.loc[k, 'initial_sl'] += 3e-5
        write_trades(far, tpath)
        code, out = run_cli(args)
        self.assertEqual(code, 1)
        self.assertIn('判定: 不合格', out)
        code, _ = run_cli(['--bars', os.path.join(d, 'nothing.csv'), '--trades', tpath, '--symbol', 'EURUSD'])
        self.assertEqual(code, 2)                               # 入力の誤り


class OffsetParity(unittest.TestCase):
    """サーバー時間が NY+7 でないブローカー（--offset、EA の InpServerOffsetHours）"""

    def test_offset_round_trip_and_wrong_offset(self):
        bars = holiday_h1(4000)
        srv = bars.copy()
        srv.index = bars.index + 2 * HOUR                     # サーバー時間 = NY+9
        py0 = mp.run_python(bars, 'EURUSD')
        py2 = mp.run_python(srv, 'EURUSD', offset_h=2)
        t2 = py2.trades.copy()
        for c in ('entry_time', 'exit_time', 'key_time'):
            t2[c] = t2[c] - 2 * HOUR
        pd.testing.assert_frame_equal(t2, py0.trades)           # 時刻がずれるだけで、取引は同じ
        e2 = py2.evals.copy()
        for c in ('bar_time', 'key_time'):
            e2[c] = e2[c] - 2 * HOUR
        pd.testing.assert_frame_equal(e2, py0.evals)
        with tempfile.TemporaryDirectory() as d:
            paths = mp.write_python_logs(py2, d)
            # NY+7 の金曜 22:00・23:00 はサーバー時間の土曜 00:00・01:00。土日の判定は換算後の曜日で行う
            self.assertEqual(len(mp.read_bars(paths['bars'], 2)), len(bars))
            self.assertLess(len(fd.load_mt5_csv(paths['bars'])), len(bars))
            res = mp.run_parity(paths['bars'], paths['trades'], 'EURUSD', eval_path=paths['eval'])
            self.assertEqual(res.offset_h, 2)                   # _info.csv の server_offset_h を使う
            self.assertTrue(res.exact)
            bad = mp.run_parity(paths['bars'], paths['trades'], 'EURUSD', eval_path=paths['eval'], offset=0)
            self.assertFalse(bad.exact)
            self.assertEqual(bad.ecmp.offset_shift, 2)         # T コードの並びから正しいずれを推定する
            report = mp.format_report(bad)
            self.assertIn('--offset 2', report)
            self.assertIn('土日になり', report)


class StartAlignment(unittest.TestCase):
    """EA が最初に読み込んだ足（first_bar_time）から Python を回す"""

    def test_start_from_info_eval_or_unknown(self):
        bars = holiday_h1(4000)
        py = mp.run_python(bars.iloc[1000:], 'EURUSD')         # EA は 1000 本目から読み込んだ
        with tempfile.TemporaryDirectory() as d:
            paths = mp.write_python_logs(py, d)
            full = os.path.join(d, 'full_bars.csv')            # 足の CSV はそれより前からある
            write_bars(bars, full)
            r1 = mp.run_parity(full, paths['trades'], 'EURUSD', eval_path=paths['eval'])
            self.assertTrue(r1.ctx.start_aligned)
            self.assertTrue(r1.exact)
            r2 = mp.run_parity(full, paths['trades'], 'EURUSD', eval_path=paths['eval'], use_info=False)
            self.assertTrue(r2.ctx.start_aligned)               # 評価ログの最初の足の 92 本前
            self.assertTrue(r2.exact)
            r3 = mp.run_parity(full, paths['trades'], 'EURUSD', use_info=False)
            self.assertIsNone(r3.ctx.start_aligned)             # 分からない → 足の先頭から
            self.assertTrue(r3.tcmp.mismatches)
            _, hints = mp.first_trade_detail(r3)
            self.assertEqual(hints[0]['tag'], 'window')
            first_ea = py.trades['entry_time'].min()
            r4 = mp.run_parity(full, paths['trades'], 'EURUSD', use_info=False, date_from=str(first_ea))
            self.assertGreaterEqual(r4.tcmp.dir_rate, r3.tcmp.dir_rate)


class RealAndGaps(unittest.TestCase):
    """休場明け（GAP_FALLBACK）・窓開け（SL_gap）と、自動売買の実約定ログ（_real.csv）"""

    @classmethod
    def setUpClass(cls):
        cls.py = mp.run_python(gapped_h1(), 'EURUSD')

    def test_gap_exits_round_trip(self):
        reasons = set(self.py.trades['exit_reason'])
        self.assertTrue({'GAP_FALLBACK', 'SL_gap'} <= reasons, reasons)
        with tempfile.TemporaryDirectory() as d:
            paths = mp.write_python_logs(self.py, d)
            tr, _ = mp.read_trades(paths['trades'])
            res = mp.compare_logs(self.py, tr, mp.read_eval(paths['eval']))
        self.assertTrue(res.exact)

    def real_frame(self):
        """Python の取引を実約定らしくする: 時刻は足の途中、約定は1ポイント不利、SL は5桁に丸め、窓開けは SL と記録"""
        rows = []
        for i, r in enumerate(self.py.trades.to_dict('records')):
            d = int(r['dir'])
            last = r['exit_reason'].split('+')[-1]
            rows.append(dict(entry_time=r['entry_time'] + pd.Timedelta(minutes=7 + i % 40), dir=d,
                             entry=round(r['entry'] + d * 1e-5, 5), initial_sl=round(r['initial_sl'], 5),
                             exit_time=r['exit_time'] + (pd.Timedelta(seconds=5) if last in ('WEEKEND', 'END')
                                                         else pd.Timedelta(minutes=23)),
                             exit_reason='SL' if last == 'SL_gap' else last, R=r['R'], key_time=r['key_time'],
                             score=r['score']))
        return pd.DataFrame(rows)

    def test_real_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'EURUSD_real.csv')
            write_trades(self.real_frame(), path, real=True)
            tr, real = mp.read_trades(path)
            self.assertTrue(real)                               # ticket 列 → 実約定
            res = mp.compare_logs(self.py, tr, None, real=True)
            self.assertTrue(res.passed)
            self.assertIsNone(res.tcmp.exact)                   # 実約定では完全一致は問わない
            self.assertEqual(res.tcmp.exit_rate, 1.0)           # SL_gap は SL と同じとみなす
            self.assertEqual(res.tcmp.mismatches, [])
            self.assertLessEqual(res.tcmp.sl_max_pts, 0.5 + 1e-6)
            tr2 = tr.drop(index=4).reset_index(drop=True)       # 1件を実約定側だけ見送った
            res2 = mp.compare_logs(self.py, tr2, None, real=True)
            self.assertEqual(dict(res2.tcmp.issue_count), {'PY_ONLY': 1})
            _, hints = mp.first_trade_detail(res2)
            self.assertIn('real_only', {h['tag'] for h in hints})


class Helpers(unittest.TestCase):
    def test_symbol_base_and_point(self):
        self.assertEqual(mp.symbol_base('eurusd.a'), 'EURUSD')
        self.assertEqual(mp.symbol_base('XAUUSDm'), 'XAUUSD')
        self.assertEqual(mp.symbol_base('GOLD.pro'), 'XAUUSD')
        self.assertEqual(mp.default_point('USDJPY'), 0.001)
        self.assertEqual(mp.default_point('XAUUSD'), 0.01)
        self.assertEqual(mp.default_point('EURUSD'), 0.00001)

    def test_parse_helpers(self):
        self.assertEqual(mp.parse_days('2024.12.26;2025-01-02, 2025/01/03;x'),
                         {date(2024, 12, 26), date(2025, 1, 2), date(2025, 1, 3)})
        self.assertEqual(mp.parse_time('2023.01.02 05:00'), pd.Timestamp('2023-01-02 05:00'))
        self.assertTrue(pd.isna(mp.parse_time('')))
        self.assertTrue(mp._reason_equal('SL', 'SL_gap', real=True))
        self.assertFalse(mp._reason_equal('SL', 'SL_gap', real=False))

    def test_switches_from_info(self):
        info = {'switches': 'g3=1 d1_gate=2 gap_gate=0 clear_gate=1 cf_scope=1 support_gate=0 sl_mode=1 p3=1',
                'params': 'N_BIG=12 N_SMALL=3 ZONE_ATR=0.5000 SLOPE_MIN=0.0000 ENTRY_BUF_ATR=0.0500 SL_BUF_ATR=0.2000 '
                          'R_MIN_ATR=0.8000 R_MAX_ATR=2.5000 N_D1=72 TOL_LV=0.6000 TOL_S=1.0000 CF_MIN_TOUCH=3 RR_CF=2.0000 '
                          'GAP_HI=8.0000 LVL_MAX_ATR=3.0000'}
        self.assertEqual(mp.switches_from_info(info),
                         {'g3': True, 'd1_gate': 'soft', 'clear_gate': True, 'cf_scope': 'daily', 'sl_mode': 'node',
                          'p3': True, 'R_MAX_ATR': 2.5})
        self.assertEqual(mp.config_name(mp.switches_from_info({'switches': 'g3=1'})), 'F+G3')

    def test_unsupported_configs_are_refused(self):
        bars = holiday_h1(1500)
        for v in ('F-stop', 'mincore_raw', 'naive:p=0.02:seed=1'):
            with self.assertRaises(ValueError):
                mp.run_python(bars, 'EURUSD', sw=fs.config(v))

    def test_unknown_symbol_and_extra_days_are_scoped(self):
        bars = holiday_h1(3000)
        cal, snom = fs.calendar_sets, dict(fs.S_NOM)
        with self.assertRaises(ValueError):
            mp.run_python(bars, 'NZDUSD')                      # 表にない銘柄は s_nom が要る
        py = mp.run_python(bars, 'NZDUSD', s_nom=0.00018, extra_closed={date(2015, 11, 26)},
                           extra_early={date(2015, 11, 27)})
        self.assertIs(fs.calendar_sets, cal)                    # 照合が終われば元に戻す
        self.assertEqual(fs.S_NOM, snom)
        self.assertEqual(py.s_nom, 0.00018)
        ev = py.evals
        t1 = set(ev.loc[ev['code'] == 'T1', 'bar_time'].dt.date)
        self.assertIn(date(2015, 11, 26), t1)                   # 追加の休場日
        early = ev[ev['bar_time'] == pd.Timestamp('2015-11-27 16:00')]
        self.assertEqual(list(early['code']), ['T2'])           # 追加の早仕舞い日は 17時の確定で新規停止


class IsDataParity(unittest.TestCase):
    """開発期間の実データ（FUSION_DATA_DIR の EURUSD_H1.csv。2013 年だけ使う）でも自分自身と全一致する"""

    def test_eurusd_2013(self):
        d = os.environ.get('FUSION_DATA_DIR')
        if not d or not os.path.exists(os.path.join(d, 'EURUSD_H1.csv')):
            self.skipTest('FUSION_DATA_DIR（EURUSD_H1.csv）がない')
        h1 = fd.load_prepared('EURUSD', 'H1', d)
        h1 = h1[(h1.index >= '2013-01-01') & (h1.index < '2014-01-01')]
        py = mp.run_python(h1, 'EURUSD')
        trades, funnel = fs.run_h1(h1, 'EURUSD')
        self.assertEqual(len(py.trades), len(trades))
        self.assertEqual(py.funnel, funnel)
        with tempfile.TemporaryDirectory() as tmp:
            paths = mp.write_python_logs(py, tmp)
            res = mp.run_parity(paths['bars'], paths['trades'], 'EURUSD', eval_path=paths['eval'])
        self.assertTrue(res.exact)
        self.assertEqual(res.tcmp.n_py, len(trades))


if __name__ == '__main__':
    unittest.main()
