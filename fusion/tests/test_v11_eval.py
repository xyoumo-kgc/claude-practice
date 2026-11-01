"""v1.1 の評価スクリプト（fusion/v11_eval.py）のテスト:  python -m unittest discover -s fusion/tests -t .

新しいデータ（komo135・利用者の MT5）では戦略を走らせない。開発データ（環境変数 FUSION_DATA_DIR の <銘柄>_H1.csv。
2013〜2017 の OANDA。fusion.data.prepare_oanda で作ったもの）から作った合成ファイルと、手で作った取引だけで確かめる。
FUSION_DATA_DIR がないときは、同じ暦（NY+7 の月曜0時〜金曜23時）の合成の足を使う。

FUSION_KOMO_DIR（komo135 の <銘柄>h1.csv のフォルダ）があれば、各銘柄の時刻の列だけを読むテストも走る
（価格の列は読まない。戦略も走らせない。本番の実行前の確認が時刻の理由で止まらないことと、時刻の換算を確かめる）。
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import OrderedDict
from unittest import mock

import numpy as np
import pandas as pd

from fusion import broker as bk
from fusion import data as fd
from fusion import final_eval as fe
from fusion import strategy as fs
from fusion import v11_eval as v

DEV_DIR = os.environ.get('FUSION_DATA_DIR')
KOMO_DIR = os.environ.get('FUSION_KOMO_DIR')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYN = {'EURUSD': (1, 1.10, 5), 'GBPUSD': (2, 1.30, 5), 'EURJPY': (3, 125.0, 3), 'XAUUSD': (4, 1250.0, 2)}


def synthetic_h1(sym, start, end):
    """開発データがないときの合成 H1（NY+7 の仲値。月曜0時〜金曜23時、12/25・1/1 は足なし）"""
    seed, base, digits = SYN[sym]
    idx = pd.date_range(start, end, freq='1h', inclusive='left')
    idx = idx[(idx.dayofweek < 5) & ~((idx.month == 12) & (idx.day == 25)) & ~((idx.month == 1) & (idx.day == 1))]
    rng = np.random.default_rng(seed)
    n = len(idx)
    drift = np.repeat(rng.choice([-1, 1], size=n // 300 + 1) * 0.00012, 300)[:n]
    c = 1 + np.cumsum(drift + rng.normal(0, 0.0009, n)) + 0.0006 * np.sin(np.arange(n) / 9.0)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.uniform(0, 0.0007, n)
    lo = np.minimum(o, c) - rng.uniform(0, 0.0007, n)
    df = pd.DataFrame({k: np.round(x * base, digits) for k, x in (('Open', o), ('High', h), ('Low', lo), ('Close', c))},
                      index=pd.DatetimeIndex(idx, name='Time'))
    df['Volume'] = 100.0
    return df


def dev_h1(sym, start, end):
    """開発データ（FUSION_DATA_DIR）の H1。なければ合成"""
    if DEV_DIR and os.path.exists(os.path.join(DEV_DIR, f'{sym}_H1.csv')):
        h = fd.load_prepared(sym, 'H1', DEV_DIR)
        return h[(h.index >= start) & (h.index < end)]
    return synthetic_h1(sym, start, end)


def make_dev_dir(path, syms=('EURUSD', 'GBPUSD', 'EURJPY', 'XAUUSD'), start='2015-06-01', end='2017-07-01'):
    """ドライランの --dev-dir の代わり（開発データの切り出しか合成）"""
    os.makedirs(path, exist_ok=True)
    for s in syms:
        dev_h1(s, start, end).to_csv(os.path.join(path, f'{s}_H1.csv'), float_format='%.6f')
    return path


def trades(rows):
    """[(出どころ, 銘柄, エントリー時刻, R[, 方向, 決済時刻, 決済理由])] → assign の前の取引"""
    out = []
    for i, r in enumerate(rows):
        src, sym, t, pnl = r[:4]
        d = r[4] if len(r) > 4 else 1
        x = pd.Timestamp(r[5]) if len(r) > 5 else pd.Timestamp(t) + pd.Timedelta(hours=5)
        reason = r[6] if len(r) > 6 else ('SL' if pnl < 0 else 'TRAIL')
        out.append(dict(src=src, symbol=sym, entry_time=pd.Timestamp(t), exit_time=x, direction=d, entry=1.0,
                        initial_sl=0.99, risk=0.01, pnl_r=float(pnl), exit_reason=reason, bars_held=5, mfe_r=1.0,
                        mae_r=-1.0, seq=i, sym_i=v.SYMBOLS.index(sym), src_i=v.SRC_ORDER[src]))
    return pd.DataFrame(out)


NO_CONTACT = OrderedDict(asked_on='', summary='', excluded=[], partial=[])


def contact(excluded=(), partial=(), asked_on='2026-11-01'):
    c, problems = v.parse_contact({'contact': {'asked_on': asked_on, 'excluded': list(excluded), 'partial': list(partial)}},
                                  required=True)
    assert not problems, problems
    return c


def ent(sym, a, b, reason=''):
    return {'symbol': sym, 'from': a, 'to': b, 'reason': reason}


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---------------------------------------------------------------- 定数・構成・評価に使うファイル（§5・§6・§12・§13）
class TestConstants(unittest.TestCase):
    def test_symbols_digits_and_spreads(self):
        self.assertEqual(v.SYMBOLS, ['EURUSD', 'GBPUSD', 'EURJPY', 'AUDUSD', 'USDCAD', 'AUDJPY', 'XAUUSD',
                                     'USDJPY', 'GBPJPY', 'EURGBP', 'EURCHF', 'USDCHF'])
        self.assertEqual(v.USED, fs.SYMBOL_ORDER)                    # v1.0 の番号 0〜6 と同じ
        self.assertEqual(v.NEW, ['USDJPY', 'GBPJPY', 'EURGBP', 'EURCHF', 'USDCHF'])
        self.assertEqual(len(v.FX), 11)
        self.assertNotIn('XAUUSD', v.FX)
        self.assertEqual({s: v.DIGITS[s] for s in ('USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY')}, dict.fromkeys(
            ('USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY'), 3))
        self.assertEqual(v.DIGITS['XAUUSD'], 2)
        self.assertEqual(sorted(s for s, d in v.DIGITS.items() if d == 5),
                         sorted(['EURUSD', 'GBPUSD', 'AUDUSD', 'USDCAD', 'EURGBP', 'EURCHF', 'USDCHF']))
        self.assertEqual(dict(v.EXTRA_S_NOM), {'EURGBP': 0.00015, 'USDCHF': 0.00015, 'EURCHF': 0.00020})
        for s in v.SYMBOLS:
            want = v.EXTRA_S_NOM[s] if s in v.EXTRA_S_NOM else fs.S_NOM[s]
            self.assertEqual(v.S_NOM[s], want, s)
        for s in v.EXTRA_S_NOM:
            self.assertNotIn(s, fs.S_NOM)                           # strategy の表は変えていない（評価の間だけ足す）
        self.assertEqual(v.NAIVE_P, [0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02, 0.03, 0.05, 0.08])
        self.assertEqual(v.NAIVE_SEEDS, list(range(20)))
        self.assertEqual(v.USER_OFFSET, 100)

    def test_configs(self):
        self.assertEqual(v.CONFIGS, ['v1.1', 'fusion', 'v1.1_s1.5'])
        self.assertEqual(v.switches(v.MAIN), fs.VARIANTS['F+h1trans'])
        self.assertEqual(v.switches(v.MAIN), {'h1_transition': True})
        self.assertEqual(v.switches(v.WIDE), v.switches(v.MAIN))
        self.assertEqual(v.switches(v.REF), {})
        self.assertEqual(v.SPREAD_MULT, {v.WIDE: 1.5})
        self.assertEqual(fs.config(v.naive_name(0.0075, 3)), dict(entry='naive', naive_p=0.0075, naive_seed=3))
        self.assertEqual(fs.config(v.naive_name(0.0125, 19)), dict(entry='naive', naive_p=0.0125, naive_seed=19))

    def test_production_spec(self):
        spec = v.make_spec()
        self.assertEqual(spec['ud'], ('2020-05-15', '2022-03-04'))
        self.assertEqual(spec['ue'], ('2022-03-05', '2026-10-31'))
        self.assertEqual(spec['ux'], ('2013-03-01', '2020-05-14'))
        self.assertEqual(dict(spec['ux_from']), {'EURCHF': '2015-03-01'})
        self.assertEqual(spec['ue_after'], ('2024-09-01', '2026-10-31'))
        self.assertEqual(spec['src_check'], ('2018-01-01', '2020-05-14'))
        self.assertEqual(spec['cut'], ('EURUSD', '2021-06-01'))
        mids = v.pool_midpoints(spec)                               # 事前登録の中点と計算が一致する
        self.assertEqual(mids['U-D'], pd.Timestamp('2021-04-09 12:00'))
        self.assertEqual(mids['U-E'], pd.Timestamp('2024-07-03 00:00'))
        with self.assertRaises(ValueError):
            v.pool_midpoints(dict(spec, midpoints={'U-D': '2021-04-09 00:00'}))
        self.assertEqual(len(pd.period_range(*spec['psr_months'], freq='M')), 78)
        lo, hi = v.day_range(*spec['ue'])
        self.assertAlmostEqual(12 * (hi - lo) / pd.Timedelta(days=365.25), 55.9, places=1)      # §10 の U-E 55.9
        lo, hi = v.day_range(*spec['ud'])
        self.assertAlmostEqual(12 * (hi - lo) / pd.Timedelta(days=365.25), 21.7, places=1)      # §10 の U-D 21.7
        self.assertEqual((spec['min_symbols'], spec['min_symyears']), (8, 30.0))
        self.assertEqual((spec['komo_rows'], spec['komo_last']), (57600, '2022-03-04 23:00'))
        # §3.2: 利用者の系列で使う足・最初の足の規則、§8: PSR の期間、§3.2 の時刻の判定、§7.2 の期限
        self.assertEqual(spec['mt5_clip'], ('2021-12-01', '2026-10-31'))
        self.assertEqual((spec['ue_late'], spec['ue_drop']), ('2021-12-01', '2023-01-01'))
        self.assertEqual(spec['psr_months'], ('2020-05', '2026-10'))
        self.assertEqual((v.CLOCK_NEED, v.CLOCK_MIN_BARS, v.INT_TOL), (0.95, 100, 1e-6))
        self.assertEqual(v.STAGE2_DEADLINE, pd.Timestamp('2027-02-01'))
        self.assertEqual((v.P2_MIN_N, v.P2_FRAC, v.P4_MARGIN, v.P6_MIN, v.NAIVE_TOL), (30, 0.60, 0.10, 0.95, 0.20))
        self.assertEqual((v.TEN_MONTH_MIN, v.GAP_PER_YEAR_MAX), (15, 1.0))
        # §8・§9: 月ブロック（10,000回、seed=12345）と P1 の t≥2.0 は final_eval の既定に頼る。報告書の記載もこの値
        self.assertEqual((fe.BOOT_REPS, fe.SEED_MONTH, fe.P1_T), (10000, 12345, 2.0))
        with open(os.path.join(ROOT, 'fusion', 'v11_eval.py'), encoding='utf-8') as f:
            self.assertIn('seeds=OrderedDict(month_block=12345, reps=10000,', f.read())

    def test_dry_spec_stays_in_development_data(self):
        d = v.make_spec(dry_run=True)
        self.assertTrue(d['dry_run'])
        self.assertTrue(set(d['dry_alias'].values()) <= {'EURUSD', 'GBPUSD', 'EURJPY', 'XAUUSD'})
        self.assertEqual(d['symbols'], [s for s in v.SYMBOLS if s in d['dry_alias']])
        for key in ('komo_clip', 'ud', 'ux', 'ue', 'ue_after', 'src_check', 'mt5_clip'):
            lo, hi = v.day_range(*d[key])
            self.assertGreaterEqual(lo, pd.Timestamp('2013-01-01'), key)
            self.assertLessEqual(hi, pd.Timestamp('2018-01-01'), key)
        self.assertLess(v.day_range(*d['ud'])[1], v.day_range(*d['ue'])[0] + pd.Timedelta(days=1))   # 判定プールは重ならない
        self.assertIsNone(d['ref_trades'])
        v.pool_midpoints(d)

    def test_eval_files_and_imports(self):
        self.assertEqual(v.EVAL_FILES, list(fe.EVAL_FILES) + ['fusion/PREREGISTRATION_v1_1.md', 'fusion/v11_eval.py'])
        for f in v.EVAL_FILES:
            self.assertTrue(os.path.exists(os.path.join(ROOT, f)), f)
        out = subprocess.run([sys.executable, '-c', 'import sys, fusion.v11_eval; print("\\n".join(sorted('
                              'm.__file__ for n, m in sys.modules.items() if n.split(".")[0] == "fusion")))'],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        self.assertTrue(out)
        for p in out:                                               # 読み込む fusion のモジュールは、すべて評価に使うファイル
            self.assertIn(os.path.relpath(p, ROOT).replace(os.sep, '/'), v.EVAL_FILES)

    def test_final_eval_functions_used(self):
        """§12: final_eval から使うのは定数に頼らない関数だけ"""
        with open(os.path.join(ROOT, 'fusion', 'v11_eval.py'), encoding='utf-8') as f:
            src = f.read()
        used = set(re.findall(r'\bfe\.(\w+)', src)) - {'EVAL_FILES'}
        allowed = {'summary', 'month_block_ci', 'monthly_r', 'sharpe', 'moments', 'deflated_sharpe', 'drop_top',
                   'judge_p1', 'judge_p3', 'judge_p5'}
        self.assertTrue(used <= allowed, used - allowed)
        for name in ('assign', 'pool_midpoints', 'config_block', 'to_frame', 'symbol_years', 'judge_p6', 'dsr_block',
                     'expected_max_sr'):
            self.assertNotIn(name, used)
        self.assertNotRegex(src, r'from fusion\.final_eval import')

    def test_git_state_and_problems(self):
        g = v.git_state()
        self.assertTrue(g['commit'])
        self.assertTrue(g['prereg_commit'])
        self.assertIsInstance(g['eval_files_dirty'], list)
        clean = dict(commit='abc', prereg_commit='def', eval_files_dirty=[], eval_files_untracked=[])
        self.assertEqual(v.git_problems(clean), [])
        for bad in (dict(clean, commit=None), dict(clean, prereg_commit=None), dict(clean, eval_files_dirty=None),
                    dict(clean, eval_files_dirty=['fusion/v11_eval.py']),
                    dict(clean, eval_files_untracked=['fusion/v11_eval.py'])):
            self.assertEqual(len(v.git_problems(bad)), 1, bad)


# ---------------------------------------------------------------- strategy の表の一時的な追加・仕事ごとの差し替え（§12）
class TestTables(unittest.TestCase):
    def test_install_and_restore(self):
        order0, snom0 = fs.SYMBOL_ORDER, dict(fs.S_NOM)
        with v.tables_installed():
            self.assertIs(fs.S_NOM, bk.NOMINAL_SPREAD)
            for i, s in enumerate(v.SYMBOLS):
                self.assertEqual(fs.SYMBOL_ORDER.index(s), i, s)    # 7銘柄は v1.0 と同じ 0〜6、新しい5銘柄は 7〜11
            for s, x in v.EXTRA_S_NOM.items():
                self.assertEqual(fs.S_NOM[s], x)
                self.assertEqual(bk.NOMINAL_SPREAD[s], x)
            with self.assertRaises(RuntimeError):                   # 二重に足さない
                v.install_tables()
        self.assertIs(fs.SYMBOL_ORDER, order0)
        self.assertEqual(fs.SYMBOL_ORDER, v.USED)
        self.assertEqual(dict(fs.S_NOM), snom0)

    def test_job_tables_restore(self):
        with self.assertRaises(RuntimeError):                       # 表を足さずに仕事をしない
            with v.job_tables('komo', 'EURUSD', v.MAIN):
                pass
        with v.tables_installed():
            order = fs.SYMBOL_ORDER
            with v.job_tables('komo', 'EURGBP', v.WIDE):
                self.assertAlmostEqual(fs.S_NOM['EURGBP'], 1.5 * 0.00015, places=15)
                self.assertEqual(fs.S_NOM['EURUSD'], 0.0001)        # ほかの銘柄は変えない
            self.assertEqual(fs.S_NOM['EURGBP'], 0.00015)
            with v.job_tables('mt5', 'EURUSD', v.naive_name(0.02, 1)):
                self.assertEqual(fs.SYMBOL_ORDER.index('EURUSD'), 100)
                self.assertEqual(fs.SYMBOL_ORDER.index('XAUUSD'), 106)
                self.assertEqual(fs.SYMBOL_ORDER.index('USDCHF'), 111)
            self.assertIs(fs.SYMBOL_ORDER, order)
            with v.job_tables('komo', 'USDCHF', v.naive_name(0.02, 1)):
                self.assertEqual(fs.SYMBOL_ORDER.index('USDCHF'), 11)
            with v.job_tables('mt5', 'EURCHF', v.MAIN):             # 利用者の系列でも素朴ベースライン以外は差し替えない
                self.assertEqual(fs.SYMBOL_ORDER.index('EURCHF'), 10)
            with self.assertRaises(ZeroDivisionError):              # 途中で失敗しても必ず戻す
                with v.job_tables('mt5', 'GBPJPY', v.WIDE):
                    fs.SYMBOL_ORDER = [None] * 5
                    1 / 0
            self.assertIs(fs.SYMBOL_ORDER, order)
            self.assertEqual(fs.S_NOM['GBPJPY'], 0.025)
            fs.S_NOM['EURUSD'] = 0.00015                           # 前の仕事の差し替えが残っていたら走らせない
            try:
                with self.assertRaises(RuntimeError):
                    with v.job_tables('komo', 'EURUSD', v.MAIN):
                        pass
            finally:
                fs.S_NOM['EURUSD'] = 0.0001

    def test_v10_naive_sequence_unchanged(self):
        """7銘柄の素朴ベースラインの乱数の系列は v1.0 と同じ（表を足しても 7銘柄の番号は変わらない）。
        開発データのない AUDUSD・USDCAD・AUDJPY は、別の銘柄の足に名前を付け替えて走らせる"""
        alias = {'EURUSD': 'EURUSD', 'GBPUSD': 'GBPUSD', 'EURJPY': 'EURJPY', 'AUDUSD': 'EURUSD', 'USDCAD': 'GBPUSD',
                 'AUDJPY': 'EURJPY', 'XAUUSD': 'XAUUSD'}
        self.assertEqual(sorted(alias), sorted(v.USED))
        cfg = fs.config(v.naive_name(0.05, 7))
        for sym in v.USED:
            h = dev_h1(alias[sym], '2016-01-01', '2016-05-01')
            before, _ = fs.run_h1(h, sym, cfg)                     # v1.0 のまま
            with v.tables_installed(), v.job_tables('komo', sym, v.naive_name(0.05, 7)):
                after, _ = fs.run_h1(h, sym, cfg)
            self.assertGreater(len(before), 3, sym)
            self.assertEqual(pd.DataFrame(before).to_dict('list'), pd.DataFrame(after).to_dict('list'), sym)


# ---------------------------------------------------------------- 合成の入力ファイル（開発データから）
class Inputs:
    """komo135 の形・MT5 の形のファイルを開発データから作る（テスト用）"""

    def __init__(self, tmp):
        self.tmp = tmp

    def komo(self, sym, src, start, end):
        p = os.path.join(self.tmp, 'komo', f'{sym}h1.csv')
        v.write_komo_file(p, dev_h1(src, start, end), sym)
        return p

    def mt5(self, sym, src, start, end, clock, sub='mt5'):
        p = os.path.join(self.tmp, sub, f'{sym}_H1.csv')
        v.write_mt5_file(p, dev_h1(src, start, end), sym, clock)
        return p


class TestRunner(unittest.TestCase):
    """新しい5銘柄の通り道・乱数の種・仕事の順番（開発データの系列を新しい銘柄名で走らせる）"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='v11_runner_')
        inp = Inputs(cls.tmp)
        cls.komo = OrderedDict()
        for sym, src in (('EURUSD', 'EURUSD'), ('XAUUSD', 'XAUUSD'), ('USDJPY', 'EURJPY'), ('GBPJPY', 'EURJPY'),
                         ('EURGBP', 'EURUSD'), ('EURCHF', 'EURUSD'), ('USDCHF', 'GBPUSD')):
            cls.komo[sym] = inp.komo(sym, src, '2016-01-01', '2016-07-01')
        cls.mt5 = OrderedDict((s, inp.mt5(s, src, '2016-02-01', '2016-07-01', {'kind': 'fixed', 'hours': 0}))
                              for s, src in (('EURUSD', 'EURUSD'), ('USDCHF', 'GBPUSD')))
        cls.ctx = dict(komo=dict(cls.komo), komo_clip=None, mt5=dict(cls.mt5), mt5_clip=('2016-01-01', '2016-12-31'),
                       clock={'kind': 'fixed', 'hours': 0})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_jobs(self, jobs):
        with v.Runner(self.ctx, 1, lambda s: None) as rn:
            out = rn.run(jobs)
        self.assertEqual(fs.SYMBOL_ORDER, v.USED)                   # 終わったら元に戻す
        for s in v.EXTRA_S_NOM:
            self.assertNotIn(s, fs.S_NOM)
        return out

    def test_new_symbols_spread_and_numbers(self):
        """新しい5銘柄: s_nom の追加（約定に使うスプレッド）と、素朴ベースラインの番号 7〜11（利用者の系列は 107〜111）"""
        seen, seeds = [], []
        real_broker, real_rng = bk.Broker, np.random.default_rng

        def broker(spread=0.0):
            seen.append(spread)
            return real_broker(spread)

        def rng(seed=None):
            seeds.append(seed)
            return real_rng(seed)
        jobs = [('komo', s, c, None) for s in v.NEW for c in (v.MAIN, v.WIDE, v.naive_name(0.05, 2))]
        jobs += [('mt5', 'USDCHF', v.naive_name(0.05, 2), None), ('komo', 'EURUSD', v.naive_name(0.05, 2), None),
                 ('mt5', 'EURUSD', v.naive_name(0.05, 2), None), ('komo', 'XAUUSD', v.naive_name(0.05, 2), None)]
        with mock.patch.object(bk, 'Broker', side_effect=broker), mock.patch('numpy.random.default_rng', side_effect=rng):
            out = self.run_jobs(jobs)
        k = 0
        for job in jobs:
            src, sym, cfg, _ = job
            want = v.S_NOM[sym] * (1.5 if cfg == v.WIDE else 1.0)
            self.assertAlmostEqual(seen[k], want, places=15, msg=job)
            k += 1
        self.assertEqual(seeds, [2000 + v.SYMBOLS.index(s) for s in v.NEW] + [2111, 2000, 2100, 2006])
        for job, (df, _, _) in out.items():
            self.assertTrue((df['symbol'] == job[1]).all())
        self.assertGreater(sum(len(out[j][0]) for j in jobs if j[2] == v.MAIN), 0)

    def test_order_does_not_matter(self):
        """仕事の順番を変えても結果が変わらない（1.5倍の構成の後に走らせた構成、利用者の系列の素朴ベースラインの後の komo135 を含む）"""
        jobs = [('komo', 'EURGBP', v.WIDE, None), ('komo', 'EURGBP', v.MAIN, None), ('komo', 'EURGBP', v.REF, None),
                ('mt5', 'EURUSD', v.naive_name(0.05, 1), None), ('komo', 'EURUSD', v.naive_name(0.05, 1), None),
                ('komo', 'USDJPY', v.WIDE, None), ('komo', 'USDJPY', v.naive_name(0.05, 1), None),
                ('mt5', 'EURUSD', v.WIDE, None), ('mt5', 'EURUSD', v.MAIN, None), ('komo', 'EURUSD', v.MAIN, '2016-05-02')]
        a = self.run_jobs(jobs)
        b = self.run_jobs(list(reversed(jobs)))
        for job in jobs:
            alone = self.run_jobs([job])[job][0]                    # 1件だけで走らせたもの（前の仕事の影響がない）
            self.assertTrue(a[job][0].equals(b[job][0]), job)
            self.assertTrue(a[job][0].equals(alone), job)
        self.assertFalse(a[('komo', 'EURGBP', v.WIDE, None)][0][['entry', 'pnl_r']].equals(
            a[('komo', 'EURGBP', v.MAIN, None)][0][['entry', 'pnl_r']]))       # 1.5倍は取引そのものを変えうる
        self.assertFalse(a[('mt5', 'EURUSD', v.naive_name(0.05, 1), None)][0]['entry_time'].tolist()
                         == a[('komo', 'EURUSD', v.naive_name(0.05, 1), None)][0]['entry_time'].tolist())

    def test_naive_kept_from_pool_start(self):
        """素朴ベースラインは系列の先頭から走らせ、判定プールの始まり以降のエントリーだけを持ち帰る（ほかの構成は絞らない）"""
        nv = ('komo', 'EURUSD', v.naive_name(0.05, 1), None)
        nv_mt5 = ('mt5', 'EURUSD', v.naive_name(0.05, 1), None)
        main = ('komo', 'EURUSD', v.MAIN, None)
        full = self.run_jobs([nv, nv_mt5, main])
        ctx = dict(self.ctx, naive_from={'komo': pd.Timestamp('2016-04-01'), 'mt5': pd.Timestamp('2016-05-02')})
        with v.Runner(ctx, 1, lambda s: None) as rn:
            out = rn.run([nv, nv_mt5, main])
        for job, at in ((nv, '2016-04-01'), (nv_mt5, '2016-05-02')):
            a, b = out[job][0], full[job][0]
            self.assertTrue(a.equals(b[b['entry_time'] >= pd.Timestamp(at)].reset_index(drop=True)), job)
            self.assertGreater(len(b), len(a), job)                 # 前の部分は捨てた（乱数の列は先頭からのまま）
            self.assertGreater(len(a), 0, job)
            self.assertEqual(out[job][2]['trades_all'], len(b))
        self.assertTrue(out[main][0].equals(full[main][0]))
        self.assertLess(out[main][0]['entry_time'].min(), pd.Timestamp('2016-04-01'))

    def test_spread_alignment_is_not_scaled(self):
        """仲値にそろえる s_nom/2 は1.5倍にしない（1.5倍の仕事の中で系列を初めて読んでも同じ足）"""
        with v.tables_installed():
            v._CTX.clear()
            v._CTX.update(self.ctx, cache={})
            with v.job_tables('komo', 'EURGBP', v.WIDE):
                h_in = v._series('komo', 'EURGBP').copy()
            v._CTX['cache'].clear()
            h_out = v._series('komo', 'EURGBP')
            v._CTX.clear()
        self.assertTrue(h_in.equals(h_out))
        raw = pd.read_csv(self.komo['EURGBP'])
        np.testing.assert_allclose(h_out['Close'].to_numpy(), raw['close'].to_numpy() / 1e5 + 0.00015 / 2, rtol=0,
                                   atol=1e-12)


# ---------------------------------------------------------------- komo135 の読み込み（§3.1）
class TestKomoLoading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='v11_komo_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, rows, header='Date,open,high,low,close,tick_volume'):
        p = os.path.join(self.tmp, name)
        with open(p, 'w') as f:
            f.write(header + '\n' + '\n'.join(rows) + '\n')
        return p

    def test_rounding_and_digits(self):
        """価格＝round(生の値)÷10^桁。浮動小数の端数を丸め、桁は円のペア3・XAUUSD 2・ほか5。四本値に s_nom/2"""
        p = self.write('EURUSDh1.csv', ['2021-03-01 00:00:00,127800.99999999,127850.0000001,127790,127820.0,10',
                                        '2021-03-01 01:00:00,127820,127830,127810,127815,11'])
        h, info = v.load_komo(p, 'EURUSD')
        np.testing.assert_allclose(h.iloc[0][v.PRICE].to_numpy(), np.array([127801, 127850, 127790, 127820]) / 1e5 + 0.00005,
                                   rtol=0, atol=1e-12)
        self.assertTrue(info['int_check'])
        self.assertEqual(info['raw_fraction_values'], 0)            # 1e−6 未満は浮動小数の誤差
        self.assertEqual(info['digits'], 5)
        self.assertEqual(info['rows'], 2)
        self.assertEqual(len(info['sha256']), 64)
        p = self.write('USDJPYh1.csv', ['2021-03-01 00:00:00,110123,110200,110100,110150,1'])
        h, _ = v.load_komo(p, 'USDJPY')
        self.assertAlmostEqual(h['Open'].iloc[0], 110.123 + 0.005, places=12)
        p = self.write('XAUUSDh1.csv', ['2021-03-01 01:00:00,180012,180100,179900,180050,1'])
        h, _ = v.load_komo(p, 'XAUUSD')
        self.assertAlmostEqual(h['Open'].iloc[0], 1800.12 + 0.15, places=9)
        p = self.write('EURCHFh1.csv', ['2021-03-01 00:00:00,108000,108010,107990,108005,1'])
        h, info = v.load_komo(p, 'EURCHF')
        self.assertAlmostEqual(h['Open'].iloc[0], 1.08 + 0.0001, places=12)    # 表にない3銘柄の s_nom（0.00020）
        self.assertEqual(info['s_nom'], 0.0002)

    def test_checks_and_problems(self):
        spec = dict(v.make_spec(), komo_rows=2, komo_last='2021-03-01 01:00')
        ok = self.write('EURGBPh1.csv', ['2021-03-01 00:00:00,86000.00000000001,86010,85989.99999999999,86005,1',
                                         '2021-03-01 01:00:00,86005,86010,85990,86000,1'])
        _, info = v.load_komo(ok, 'EURGBP')
        self.assertTrue(info['int_check'])                          # 浮動小数の端数（1e−11 程度）だけなら通る
        self.assertEqual(info['raw_fraction_values'], 0)
        self.assertLess(info['int_check_max_dev'], 1e-9)
        self.assertEqual([p for p in v.komo_problems(info, 'EURGBP', spec) if 'ウォームアップ' not in p], [])
        self.assertTrue(any('ウォームアップ' in p for p in v.komo_problems(info, 'EURGBP', spec)))   # U-X の銘柄は 2012-12-01 まで
        nan = self.write('GBPUSDh1.csv', ['2021-03-01 00:00:00,,130010,129990,130005,1',
                                          '2021-03-01 01:00:00,130005,130010,129990,130000,1'])
        _, info = v.load_komo(nan, 'GBPUSD')
        self.assertFalse(info['int_check'])
        self.assertTrue(any('整数倍' in p for p in v.komo_problems(info, 'GBPUSD', spec)))
        dec = self.write('AUDUSDh1.csv', ['2021-03-01 00:00:00,0.71234,0.71300,0.71200,0.71250,1',
                                          '2021-03-01 01:00:00,0.71250,0.71300,0.71200,0.71260,1'])
        _, info = v.load_komo(dec, 'AUDUSD')
        self.assertTrue(any('整数の形式' in p for p in v.komo_problems(info, 'AUDUSD', spec)))
        short = dict(spec, komo_rows=57600, komo_last='2022-03-04 23:00')
        _, info = v.load_komo(ok, 'EURGBP')
        probs = v.komo_problems(info, 'EURGBP', short)
        self.assertTrue(any('行数' in p for p in probs))
        self.assertTrue(any('最終の足' in p for p in probs))
        with self.assertRaises(ValueError):
            v.load_komo(self.write('bad.csv', ['2021-03-01 00:00:00,1,1,1,1'], header='Time,O,H,L,C'), 'EURUSD')

    def test_one_real_fraction_stops(self):
        """§3.1 の整数倍の確認は丸める前の生の値で行う（丸めた後だと必ず通る）。本物の端数が1つでもあれば止める理由にする"""
        spec = dict(v.make_spec(), komo_rows=3, komo_last='2021-03-01 02:00')
        rows = ['2021-03-01 00:00:00,127800,127900,127700,127850,1',
                '2021-03-01 01:00:00,127850,127900,127700,127800.5,1',             # 本物の端数（0.5 ポイント）
                '2021-03-01 02:00:00,127800.00000000001,127900,127700,127810,1']  # 浮動小数の端数（数えない）
        h, info = v.load_komo(self.write('EURUSDh1.csv', rows), 'EURUSD')
        self.assertFalse(info['int_check'])
        self.assertEqual((info['raw_fraction_values'], info['raw_fraction_rows']), (1, 1))
        self.assertAlmostEqual(info['int_check_max_dev'], 0.5)
        probs = v.komo_problems(info, 'EURUSD', spec)
        self.assertEqual(len(probs), 1)
        self.assertIn('整数倍', probs[0])
        self.assertNotIn('大半', probs[0])
        self.assertAlmostEqual(h['Close'].iloc[1], 1.278 + 0.00005, places=12)   # 変換そのもの（round）は事前登録どおり

    def test_athens_to_ny7(self):
        """Europe/Athens → UTC → NY+7。通常の週は変わらず、米欧の夏時間がずれる週だけ1時間後ろにずれる"""
        cases = [('2021-03-01 00:00', '2021-03-01 00:00'), ('2021-03-05 23:00', '2021-03-05 23:00'),   # 冬（どちらも標準時）
                 ('2021-03-15 00:00', '2021-03-15 01:00'), ('2021-03-19 22:00', '2021-03-19 23:00'),   # 米だけ夏時間
                 ('2021-03-14 23:00', '2021-03-15 00:00'),                                             # ずれる週の日曜23時
                 ('2021-07-05 00:00', '2021-07-05 00:00'), ('2021-07-09 23:00', '2021-07-09 23:00'),   # 夏
                 ('2021-11-01 00:00', '2021-11-01 01:00'), ('2021-11-05 22:00', '2021-11-05 23:00'),   # 欧だけ標準時に戻った
                 ('2021-11-08 00:00', '2021-11-08 00:00')]
        got = v.athens_to_server(pd.DatetimeIndex([a for a, _ in cases]))
        self.assertEqual(list(got), [pd.Timestamp(b) for _, b in cases])
        for bad in ('2021-03-28 03:30', '2021-10-31 03:30'):        # 夏時間の切り替えの抜け・重なり → 例外
            with self.assertRaises(Exception):
                v.athens_to_server(pd.DatetimeIndex([bad]))

    def test_weekend_and_duplicates_after_conversion(self):
        """換算してから土日を除く（ずれる週の日曜23時の足は月曜0時になって残る）。同じ時刻は最初の足"""
        p = self.write('EURUSDh1.csv', ['2021-03-14 23:00:00,100000,100010,99990,100005,1',     # 日曜23時（ずれる週）
                                        '2021-03-15 00:00:00,100005,100010,99990,100000,2',
                                        '2021-03-15 00:00:00,100100,100110,100090,100105,3',     # 重複 → 最初を使う
                                        '2021-03-13 10:00:00,100000,100010,99990,100005,4',      # 土曜 → 除く
                                        '2021-03-15 01:00:00,100000,100010,99990,100005,5'])
        h, info = v.load_komo(p, 'EURUSD')
        self.assertEqual(list(h.index), [pd.Timestamp('2021-03-15 00:00'), pd.Timestamp('2021-03-15 01:00'),
                                         pd.Timestamp('2021-03-15 02:00')])
        self.assertEqual(h['Volume'].tolist(), [1.0, 2.0, 5.0])
        self.assertEqual((info['weekend_dropped'], info['duplicates'], info['sorted']), (1, 1, True))
        p = self.write('EURJPYh1.csv', ['2021-03-02 01:00:00,100000,100010,99990,100005,1',      # 並びが逆 → 時刻順にする
                                        '2021-03-02 00:00:00,100000,100010,99990,100005,2'])
        h, info = v.load_komo(p, 'EURJPY')
        self.assertEqual((h['Volume'].tolist(), info['sorted']), ([2.0, 1.0], False))

    def test_roundtrip_from_development_data(self):
        h = dev_h1('EURUSD', '2016-01-01', '2017-07-01')
        p = os.path.join(self.tmp, 'EURUSDh1.csv')
        v.write_komo_file(p, h, 'EURUSD')
        raw = pd.read_csv(p)
        self.assertGreater(int((pd.to_datetime(raw['Date']) != h.index).sum()), 0)   # ファイルの時刻は欧州連動の時計
        got, info = v.load_komo(p, 'EURUSD')
        self.assertTrue(got.index.equals(h.index))
        want = np.round((h[v.PRICE].to_numpy() - 0.00005) * 1e5) / 1e5 + 0.00005      # Bid を5桁の整数にした分だけ丸まる
        np.testing.assert_allclose(got[v.PRICE].to_numpy(), want, rtol=0, atol=1e-12)
        np.testing.assert_allclose(got[v.PRICE].to_numpy(), h[v.PRICE].to_numpy(), rtol=0, atol=5.0001e-6)
        self.assertEqual((info['weekend_dropped'], info['duplicates']), (0, 0))
        clip, _ = v.load_komo(p, 'EURUSD', clip=('2016-03-01', '2016-03-31'))
        self.assertEqual((clip.index[0], clip.index[-1]), (pd.Timestamp('2016-03-01'), pd.Timestamp('2016-03-31 23:00')))

    def test_find_komo_files(self):
        os.makedirs(os.path.join(self.tmp, 'repo', 'USDJPY'))
        open(os.path.join(self.tmp, 'repo', 'USDJPY', 'USDJPYh1.csv'), 'w').close()
        open(os.path.join(self.tmp, 'EURUSDh1.csv'), 'w').close()
        self.assertEqual(list(v.find_komo_files(self.tmp, v.SYMBOLS)), ['EURUSD'])
        self.assertEqual(list(v.find_komo_files(os.path.join(self.tmp, 'repo'), v.SYMBOLS)), ['USDJPY'])


@unittest.skipUnless(KOMO_DIR and os.path.exists(os.path.join(KOMO_DIR or '', 'EURUSDh1.csv')),
                     'FUSION_KOMO_DIR（komo135 の EURUSDh1.csv）がない')
class TestKomoTimesOnly(unittest.TestCase):
    """komo135 の時刻の列（Date）だけを読む（価格の列は読まない。戦略は走らせない）"""

    def test_weeks_end_at_23_after_conversion(self):
        t = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(os.path.join(KOMO_DIR, 'EURUSDh1.csv'), usecols=['Date'])['Date'],
                                            format='ISO8601'))
        self.assertEqual((len(t), t[-1]), (57600, pd.Timestamp('2022-03-04 23:00')))
        srv = v.athens_to_server(t)
        self.assertEqual(int((srv.dayofweek >= 5).sum()), 0)
        self.assertTrue(srv.is_monotonic_increasing and not srv.has_duplicates)
        used = [r for r in v.week_rows(srv[srv >= '2015-01-01']) if not r['holiday'] and r['bars'] >= 100]
        self.assertGreater(len(used), 300)
        for r in used:                                              # 換算後は、どの週も金曜23時の足で終わる
            self.assertEqual((r['last'].dayofweek, r['last'].hour), (4, 23), r['week_start'])
        ck = v.detect_clock({'EURUSD': t[t >= '2015-01-01']})       # 第2段の判定の規則でも ②（欧州連動）になる
        self.assertEqual(ck['kind'], 'athens')
        self.assertLess(ck['frac_ny7'], 0.95)

    def test_time_preconditions_of_all_files(self):
        """本番の実行前の確認のうち時刻に関わるもの（行数・最終の足・換算で例外にならない・U-X の銘柄の3か月のウォームアップ）を、
        各銘柄の時刻の列だけで確かめる（本番が時刻の理由で止まらないこと）"""
        spec = v.make_spec()
        seen = []
        for s in v.SYMBOLS:
            p = os.path.join(KOMO_DIR, f'{s}h1.csv')
            if not os.path.exists(p):
                continue
            with self.subTest(symbol=s):
                t = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(p, usecols=['Date'])['Date'], format='ISO8601'))
                self.assertEqual((len(t), t.max()), (spec['komo_rows'], pd.Timestamp(spec['komo_last'])))
                srv = v.athens_to_server(t)                         # 夏時間の重なり・抜けに当たる足がない
                self.assertTrue(srv.is_monotonic_increasing and not srv.has_duplicates)
                self.assertLessEqual(int((srv.dayofweek >= 5).sum()), 2)   # 換算後に土日に入る足は、あっても数本（除く）
                if s in v.NEW:
                    self.assertLessEqual(srv.min(), pd.Timestamp(spec['ux_first_by']))
                seen.append(s)
        self.assertIn('EURUSD', seen)


# ---------------------------------------------------------------- 利用者の MT5 の時刻の判定と換算（§3.2）
CLOCKS = OrderedDict([('ny7', {'kind': 'ny7', 'hours': 0}), ('athens', {'kind': 'athens', 'hours': 0}),
                      ('utc', {'kind': 'fixed', 'hours': 0}), ('jst', {'kind': 'fixed', 'hours': 9})])


class TestMt5Clock(unittest.TestCase):
    """開発データの時刻を NY+7・欧州連動・UTC・JST の4通りに書き換えた MT5 形式のファイルで、判定と換算で元の時刻に戻ること"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='v11_mt5_')
        cls.inp = Inputs(cls.tmp)
        cls.h = OrderedDict((s, dev_h1(s, '2016-01-04', '2017-07-01')) for s in ('EURUSD', 'GBPUSD', 'EURJPY', 'XAUUSD'))
        cls.paths = OrderedDict()
        for name, clock in CLOCKS.items():
            for s in cls.h:
                p = os.path.join(cls.tmp, name, f'{s}_H1.csv')
                v.write_mt5_file(p, cls.h[s], s, clock)
                cls.paths[(name, s)] = p

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_detect_and_convert_back(self):
        want = {'ny7': ('ny7', None), 'athens': ('athens', None), 'utc': ('fixed', 0), 'jst': ('fixed', 9)}
        for name in CLOCKS:
            raw = OrderedDict((s, v.read_mt5_raw(self.paths[(name, s)]).index) for s in self.h if s in v.FX)
            ck = v.detect_clock(raw)
            self.assertEqual((ck['kind'], ck['hours']), want[name], (name, ck['label'], ck['frac_ny7'], ck['frac_athens']))
            self.assertNotIn('XAUUSD', ck['per_symbol'])
            conv = {'kind': ck['kind'], 'hours': ck['hours'] or 0}
            for s, h in self.h.items():                             # XAUUSD にも同じ換算を使う
                got, info = v.load_mt5(self.paths[(name, s)], s, conv, ('2016-01-01', '2017-12-31'))
                self.assertTrue(got.index.equals(h.index), (name, s))
                np.testing.assert_allclose(got[v.PRICE].to_numpy(), h[v.PRICE].to_numpy(), rtol=0, atol=1e-9)
                self.assertEqual(info['duplicates'], 0)

    def test_reading_order(self):
        """生の時刻のまま読み、換算してから土日を除く（fusion.data.load_mt5_csv の順だと、日曜・土曜の生の時刻の足を失う）"""
        for name, wd in (('athens', 6), ('utc', 6), ('jst', 5)):
            p = self.paths[(name, 'EURUSD')]
            raw = v.read_mt5_raw(p)
            self.assertGreater(int((raw.index.dayofweek == wd).sum()), 0, name)    # 生の時刻には土日の足がある
            conv = dict(CLOCKS[name])
            got, info = v.load_mt5(p, 'EURUSD', conv, ('2016-01-01', '2017-12-31'))
            self.assertEqual(info['weekend_dropped'], 0, name)
            self.assertEqual(len(got), len(self.h['EURUSD']))
            self.assertLess(len(fd.load_mt5_csv(p)), len(got), name)

    def test_ny7_wins_when_no_mismatch_week(self):
        """米欧の夏時間がずれる週がないと①②の両方が当てはまる → ①"""
        h = dev_h1('EURUSD', '2016-04-04', '2016-10-29')            # 2016-03-27〜10-29 は米欧とも夏時間
        p = self.inp.mt5('EURUSD', 'EURUSD', '2016-04-04', '2016-10-29', CLOCKS['athens'], sub='summer')
        ck = v.detect_clock({'EURUSD': v.read_mt5_raw(p).index})
        self.assertEqual((ck['frac_ny7'], ck['frac_athens'], ck['kind']), (1.0, 1.0, 'ny7'))
        got, _ = v.load_mt5(p, 'EURUSD', {'kind': 'ny7', 'hours': 0}, ('2016-01-01', '2016-12-31'))
        self.assertTrue(got.index.equals(h.index))

    def test_split_weeks_recorded(self):
        """①と②の予想が違う週（米欧の夏時間がずれる週）での一致を記録する（判定の規則そのものは変えない）"""
        for name, f1, f2 in (('athens', 0.0, 1.0), ('ny7', 1.0, 0.0), ('utc', 0.0, 0.0)):
            raw = OrderedDict((s, v.read_mt5_raw(self.paths[(name, s)]).index) for s in self.h if s in v.FX)
            ck = v.detect_clock(raw)
            self.assertGreater(ck['split_weeks'], 0, name)
            self.assertLess(ck['split_weeks'], ck['weeks_used'] * 0.1, name)
            self.assertEqual((ck['frac_ny7_split'], ck['frac_athens_split']), (f1, f2), name)

    def test_clock_window(self):
        """書き出しに使う期間より前の履歴（時計の規則が違う時期）が混ざると、全週の判定と使う期間の週だけの判定が違う →
        何も計算しないうちに止める理由（§3.2 の手順で書き出し直す）。合成の時刻だけを使う（価格はない）"""
        spec = v.make_spec()

        def ny7(a, b):
            idx = pd.date_range(a, b, freq='1h', inclusive='left')
            return idx[(idx.dayofweek < 5) & ~((idx.month == 12) & (idx.day == 25)) & ~((idx.month == 1) & (idx.day == 1))]
        old = v.from_server(ny7('2015-01-05', '2021-11-27'), CLOCKS['ny7'])          # 以前は①（NY+7）の時計
        new = v.from_server(ny7('2021-12-01', '2026-11-01'), CLOCKS['athens'])       # 使う期間は②（欧州連動）
        mixed = {'EURUSD': old.append(new), 'GBPUSD': old.append(new)}
        ck = v.detect_clock(mixed)
        self.assertEqual(ck['kind'], 'ny7')                                          # 規則どおり全週で判定すると①
        w, problems = v.clock_window(mixed, spec, ck)
        self.assertEqual((w['kind'], w['same']), ('athens', False))
        self.assertLess(w['weeks_used'], ck['weeks_used'])
        self.assertEqual(len(problems), 1)
        self.assertIn('書き出し直す', problems[0])
        for raw in ({'EURUSD': new}, {'EURUSD': new.append(v.from_server(ny7('2026-11-02', '2027-01-30'), CLOCKS['athens']))},
                    {'EURUSD': v.from_server(ny7('2015-01-05', '2021-11-27'), CLOCKS['athens']).append(new)}):
            ck = v.detect_clock(raw)                                                 # 時計が同じなら、期間の外があっても同じ
            w, problems = v.clock_window(raw, spec, ck)
            self.assertEqual((ck['kind'], w['kind'], w['same'], problems), ('athens', 'athens', True, []))
        ck = v.detect_clock({'EURUSD': new})
        self.assertEqual(v.clock_window({'EURUSD': new}, spec, ck)[0]['weeks_used'], ck['weeks_used'])   # 期間どおりなら全週を使う

    def test_undecided(self):
        """どの仮説も95%に届かない → 未決（kind=None）。判定に使える週がないときも未決"""
        h = dev_h1('EURUSD', '2016-01-04', '2016-12-24')
        rng = np.random.default_rng(0)
        wk = (h.index - v.WEEK_ANCHOR) // pd.Timedelta(days=7)
        shift = pd.to_timedelta(rng.integers(0, 6, size=int(wk.max() - wk.min()) + 1)[np.asarray(wk - wk.min())], unit='h')
        ck = v.detect_clock({'EURUSD': h.index + shift})
        self.assertIsNone(ck['kind'])
        self.assertIsNone(v.detect_clock({'EURUSD': h.index[:50]})['kind'])
        self.assertIsNone(v.detect_clock({})['kind'])

    def test_week_exclusions(self):
        rows = v.week_rows(self.h['EURUSD'].index)
        hol = [r['week_start'] for r in rows if r['holiday']]
        self.assertIn(pd.Timestamp('2016-12-24 12:00'), hol)        # 12/24〜1/3 を含む週
        self.assertIn(pd.Timestamp('2016-12-31 12:00'), hol)
        self.assertNotIn(pd.Timestamp('2016-12-10 12:00'), hol)
        ck = v.detect_clock({'EURUSD': self.h['EURUSD'].index})
        ps = ck['per_symbol']['EURUSD']
        self.assertEqual(ps['weeks'], ps['used'] + ps['holiday'] + ps['short'])
        self.assertGreater(ps['used'], 60)
        for r in rows:                                              # o_w は（最後の足＋1時間）−（金曜17:00 NY の UTC）
            if not r['holiday'] and r['bars'] >= 100:
                self.assertEqual(r['o_w'], r['ny7'])                # NY+7 の時刻なら①と一致

    def test_h1_only_and_prepare(self):
        """H1 でない書き出しは、何も計算しないうちに止める理由にする。H1 なら判定・換算・期間と量まで実行前に済ませる"""
        self.assertEqual(v.bar_step(self.h['EURUSD'].index), pd.Timedelta(hours=1))
        self.assertIsNone(v.bar_step(self.h['EURUSD'].index[:1]))
        m15 = dev_h1('EURUSD', '2016-01-04', '2016-03-01').resample('15min').ffill()
        m15 = m15[m15.index.dayofweek < 5]
        p = os.path.join(self.tmp, 'm15', 'EURUSD_H1.csv')
        v.write_mt5_file(p, m15, 'EURUSD', CLOCKS['utc'])
        self.assertEqual(v.bar_step(v.read_mt5_raw(p).index), pd.Timedelta(minutes=15))
        spec = dict(v.make_spec(dry_run=True), mt5_clip=('2016-01-01', '2017-12-31'), ue=('2016-04-04', '2017-06-30'),
                    ue_late='2016-01-04', ue_drop='2016-12-01')
        problems, lines = [], []
        files = OrderedDict((s, self.paths[('jst', s)]) for s in self.h)
        ck, conv, infos, ue = v.prepare_mt5(dict(files, GBPJPY=p), spec, NO_CONTACT, problems, lines.append)
        self.assertEqual(len(problems), 1)
        self.assertIn('H1 の書き出しでない', problems[0])
        self.assertEqual((ck['kind'], conv), ('fixed', {'kind': 'fixed', 'hours': 9}))
        self.assertEqual(list(infos), list(self.h))                 # H1 でないファイルは換算もしない
        self.assertEqual(ue['usable'], list(self.h))
        self.assertTrue(any('時刻の判定' in s for s in lines))
        problems = []
        with mock.patch.object(v, 'athens_to_server', side_effect=ValueError('重なり')):
            v.prepare_mt5(OrderedDict((s, self.paths[('athens', s)]) for s in self.h), spec, NO_CONTACT, problems,
                          lambda s: None)
        self.assertEqual(len(problems), len(self.h))                # 換算の例外も実行前の確認で止める
        self.assertTrue(all('換算に失敗' in x for x in problems))

    def test_mt5_formats(self):
        """タブ区切り（MT5 の既定）・UTF-16・カンマ区切りの Date,Time を同じに読む"""
        p = self.paths[('ny7', 'EURUSD')]
        a = v.read_mt5_raw(p)
        with open(p, encoding='utf-8') as f:
            text = f.read()
        p16 = os.path.join(self.tmp, 'u16.csv')
        with open(p16, 'w', encoding='utf-16') as f:
            f.write(text)
        self.assertTrue(v.read_mt5_raw(p16).equals(a))
        pc = os.path.join(self.tmp, 'comma.csv')
        with open(pc, 'w') as f:
            f.write(text.replace('\t', ',').replace('<', '').replace('>', ''))
        self.assertTrue(v.read_mt5_raw(pc).equals(a))


# ---------------------------------------------------------------- プールへの振り分け（§3.2・§4）
class TestPools(unittest.TestCase):
    def setUp(self):
        self.spec = v.make_spec()

    def where(self, src, sym, t, c=NO_CONTACT, ue_start=None, **kw):
        d = v.assign(trades([(src, sym, t, 1.0)]), self.spec, c, ue_start or {})
        r = d.iloc[0]
        return r['pool'], r['half'], r['contact'], int(r['ue_after']), int(r['src_check'])

    def test_komo_pools(self):
        cases = [('EURUSD', '2020-05-14 23:00', ''), ('EURUSD', '2020-05-15 00:00', 'U-D'), ('XAUUSD', '2022-03-04 23:00', 'U-D'),
                 ('USDCHF', '2020-05-14 23:00', 'U-X'), ('USDCHF', '2020-05-15 00:00', 'U-D'),
                 ('USDJPY', '2013-02-28 23:00', ''), ('USDJPY', '2013-03-01 00:00', 'U-X'), ('GBPJPY', '2016-06-01 10:00', 'U-X'),
                 ('EURCHF', '2015-02-28 23:00', ''), ('EURCHF', '2015-03-01 00:00', 'U-X'),     # EURCHF は 2015-03-01 から
                 ('EURUSD', '2015-06-01 10:00', ''), ('AUDJPY', '2019-06-03 10:00', ''),        # 使用済み7銘柄は U-X に入れない
                 ('EURUSD', '2022-03-05 00:00', '')]
        for sym, t, want in cases:
            self.assertEqual(self.where('komo', sym, t)[0], want, (sym, t))
        self.assertEqual(self.where('mt5', 'EURUSD', '2021-01-04 10:00')[0], '')     # 利用者の系列は U-D に入れない

    def test_src_check_window(self):
        self.assertEqual(self.where('komo', 'EURUSD', '2017-12-31 23:00')[4], 0)
        self.assertEqual(self.where('komo', 'EURUSD', '2018-01-01 00:00')[4], 1)
        self.assertEqual(self.where('komo', 'AUDJPY', '2020-05-14 23:00')[4], 1)
        self.assertEqual(self.where('komo', 'AUDJPY', '2020-05-15 00:00')[4], 0)
        self.assertEqual(self.where('komo', 'USDJPY', '2019-01-07 10:00')[4], 0)        # 使用済み7銘柄だけ
        self.assertEqual(self.where('mt5', 'EURUSD', '2019-01-07 10:00')[4], 0)

    def test_ue_start_and_after(self):
        st = {'EURUSD': pd.Timestamp('2022-03-05'), 'USDJPY': pd.Timestamp('2022-04-03 05:00')}
        cases = [('EURUSD', '2022-03-04 23:00', ''), ('EURUSD', '2022-03-05 00:00', 'U-E'), ('USDJPY', '2022-03-10 10:00', ''),
                 ('USDJPY', '2022-04-03 05:00', 'U-E'), ('GBPUSD', '2023-01-02 10:00', ''),   # 使える銘柄でない
                 ('EURUSD', '2026-10-31 23:00', 'U-E'), ('EURUSD', '2026-11-01 00:00', '')]
        for sym, t, want in cases:
            self.assertEqual(self.where('mt5', sym, t, ue_start=st)[0], want, (sym, t))
        self.assertEqual(self.where('mt5', 'EURUSD', '2024-08-31 23:00', ue_start=st)[3], 0)
        self.assertEqual(self.where('mt5', 'EURUSD', '2024-09-01 00:00', ue_start=st)[3], 1)
        self.assertEqual(self.where('komo', 'EURUSD', '2021-09-01 00:00', ue_start=st)[3], 0)

    def test_halves(self):
        st = {'EURUSD': pd.Timestamp('2022-03-05')}
        self.assertEqual(self.where('komo', 'EURUSD', '2021-04-09 11:00')[1], '前半')
        self.assertEqual(self.where('komo', 'EURUSD', '2021-04-09 12:00')[1], '後半')
        self.assertEqual(self.where('mt5', 'EURUSD', '2024-07-02 23:00', ue_start=st)[1], '前半')
        self.assertEqual(self.where('mt5', 'EURUSD', '2024-07-03 00:00', ue_start=st)[1], '後半')
        self.assertEqual(self.where('komo', 'USDJPY', '2016-01-04 10:00')[1], '')        # U-X は分けない

    def test_contact_flags(self):
        c = contact(excluded=[{'symbol': 'EURUSD', 'from': '2021-01-01', 'to': '2021-01-31'},
                              {'symbol': '*', 'from': '2023-05-01', 'to': '2023-05-01'}],
                    partial=[{'symbol': '*', 'from': '2020-01-01', 'to': '2026-10-31'}])
        st = {'EURUSD': pd.Timestamp('2022-03-05'), 'USDJPY': pd.Timestamp('2022-03-05')}
        self.assertEqual(self.where('komo', 'EURUSD', '2021-01-31 23:00', c)[2], 'excluded')     # 両端の日を含む
        self.assertEqual(self.where('komo', 'EURUSD', '2021-02-01 00:00', c)[2], 'partial')
        self.assertEqual(self.where('komo', 'GBPUSD', '2021-01-15 10:00', c)[2], 'partial')
        self.assertEqual(self.where('mt5', 'USDJPY', '2023-05-01 23:00', c, st)[2], 'excluded')  # "*" は全銘柄
        self.assertEqual(self.where('mt5', 'USDJPY', '2023-05-02 00:00', c, st)[2], 'partial')
        self.assertEqual(self.where('komo', 'USDJPY', '2019-03-04 10:00', c)[2], '')              # U-X には当てはめない
        self.assertEqual(self.where('komo', 'EURUSD', '2019-03-04 10:00', c)[2], '')              # どのプールでもない
        d = v.assign(trades([('komo', 'EURUSD', '2021-01-10 10:00', 5.0), ('komo', 'EURUSD', '2021-02-10 10:00', -1.0),
                             ('mt5', 'EURUSD', '2023-05-01 10:00', 2.0), ('mt5', 'EURUSD', '2023-06-01 10:00', 1.0)]),
                     self.spec, c, st)
        self.assertEqual(v.judge_frame(d)['pnl_r'].tolist(), [-1.0, 1.0])     # 接触の申告で除いた取引は判定に入れない

    def test_ue_windows(self):
        def info(first, last='2026-10-30 23:00'):
            return dict(first=pd.Timestamp(first), last=pd.Timestamp(last))
        infos = OrderedDict([('EURUSD', info('2021-12-01 00:00')), ('GBPUSD', info('2022-01-03 00:00')),
                             ('EURJPY', info('2021-12-01 05:00')), ('AUDUSD', info('2023-01-01 00:00')),
                             ('USDCAD', info('2023-01-02 00:00')), ('AUDJPY', info('2021-12-01 00:00', '2025-06-30 23:00')),
                             ('XAUUSD', info('2021-12-01 00:00')), ('USDJPY', info('2021-12-01 00:00'))])
        c = contact(excluded=[{'symbol': 'XAUUSD', 'from': '2022-01-01', 'to': '2027-01-01'},
                              {'symbol': 'USDJPY', 'from': '2023-01-01', 'to': '2023-12-31'},
                              {'symbol': '*', 'from': '2024-01-01', 'to': '2024-01-10'}])
        u = v.ue_windows(infos, self.spec, c)
        r = u['rows']
        self.assertEqual(r['EURUSD']['start'], pd.Timestamp('2022-03-05'))
        self.assertEqual(r['GBPUSD']['start'], pd.Timestamp('2022-04-03'))           # 最初の足＋3か月
        self.assertEqual(r['EURJPY']['start'], pd.Timestamp('2022-03-05'))           # ＋3か月が 2022-03-05 より前
        self.assertTrue(r['AUDUSD']['usable'])                                        # 2023-01-01 ちょうどは「より後」でない
        self.assertFalse(r['USDCAD']['usable'])
        self.assertEqual(r['AUDJPY']['end'], pd.Timestamp('2025-07-01'))             # 最後の足＋1時間で終わる
        self.assertFalse(r['XAUUSD']['usable'])                                       # 期間がすべて除かれた
        self.assertAlmostEqual(r['USDJPY']['excluded_days'], 365 + 10)
        full = (pd.Timestamp('2026-10-31 00:00') - pd.Timestamp('2022-03-05')) / pd.Timedelta(days=1)
        self.assertAlmostEqual(r['EURUSD']['days'], full - 10)
        self.assertEqual(u['usable'], ['EURUSD', 'GBPUSD', 'EURJPY', 'AUDUSD', 'AUDJPY', 'USDJPY'])
        self.assertAlmostEqual(u['symbol_years'], sum(r[s]['days'] for s in u['usable']) / 365.25)
        self.assertFalse(u['ok'])                                                     # 8銘柄に届かない
        many = OrderedDict((s, info('2021-12-01 00:00', '2026-10-31 23:00')) for s in v.SYMBOLS)
        u = v.ue_windows(many, self.spec, NO_CONTACT)
        self.assertTrue(u['ok'])
        self.assertAlmostEqual(u['symbol_years'], 55.9, places=1)
        few = OrderedDict((s, info('2021-12-01 00:00', '2024-06-30 23:00')) for s in v.SYMBOLS[:8])
        self.assertFalse(v.ue_windows(few, self.spec, NO_CONTACT)['ok'])              # 8銘柄でも30銘柄年に届かない


class TestChfRule(unittest.TestCase):
    def test_cases(self):
        rows = [  # (銘柄, エントリー, 決済時刻, 決済理由, 除くか)
            ('USDCHF', '2015-01-14 10:00', '2015-01-15 00:00', 'SL', True),
            ('USDCHF', '2015-01-14 10:00', '2015-01-14 23:00', 'SL', False),
            ('USDCHF', '2015-01-14 10:00', '2015-01-15 00:00', 'WEEKEND', False),   # 決済の足は 01-14 23:00
            ('USDCHF', '2015-01-14 10:00', '2015-01-15 01:00', 'END', True),
            ('EURCHF', '2015-01-12 10:00', '2015-01-16 23:00', 'WEEKEND', True),
            ('EURCHF', '2015-01-15 23:00', '2015-01-19 00:00', 'GAP_FALLBACK', True),
            ('USDCHF', '2015-01-16 00:00', '2015-01-16 05:00', 'SL', False),       # entry_time < 2015-01-16 でない
            ('USDCHF', '2015-01-13 10:00', '2015-01-15 00:00', 'TP1+WEEKEND', False),
            ('GBPJPY', '2015-01-14 10:00', '2015-01-16 05:00', 'SL', False),
            ('USDCHF', '2014-12-01 10:00', '2015-02-01 05:00', 'TRAIL', True),
        ]
        df = trades([('komo', s, e, -1.0, 1, x, r) for s, e, x, r, _ in rows])
        self.assertEqual(v.chf_rule(df).tolist(), [w for *_, w in rows])
        spec = v.make_spec()
        d = v.assign(df, spec, NO_CONTACT)
        self.assertEqual(d['chf_excl'].tolist(), [int(w and p == 'U-X') for (*_, w), p in zip(rows, d['pool'])])
        self.assertEqual(d.loc[d['symbol'] == 'EURCHF', 'pool'].tolist(), ['', ''])   # EURCHF の U-X は 2015-03 から
        self.assertEqual(int(d['chf_excl'].sum()), 3)


# ---------------------------------------------------------------- 打ち切り・合格基準・PSR（§7〜§9）
class TestStopAndCriteria(unittest.TestCase):
    def test_stop_rule(self):
        self.assertTrue(v.stop_rule(dict(trades=400, avg_r=0.0, se=0.1))['stop'])          # ≤0 は打ち切り
        self.assertTrue(v.stop_rule(dict(trades=400, avg_r=-0.01, se=0.1))['stop'])
        self.assertTrue(v.stop_rule(dict(trades=0, avg_r=float('nan'), se=float('nan')))['stop'])
        r = v.stop_rule(dict(trades=400, avg_r=1e-9, se=0.1))
        self.assertFalse(r['stop'])
        self.assertIn('継続', r['verdict'])
        self.assertIn('打ち切り', v.stop_rule(dict(trades=1, avg_r=-1.0, se=float('nan')))['verdict'])

    def test_nse(self):
        d = trades([('komo', 'EURUSD', '2021-01-04', x) for x in (1.0, -1.0, 3.0)])
        r = v.nse(d)
        self.assertEqual(list(r), ['trades', 'avg_r', 'se'])                         # 第1段は取引数・平均R・標準誤差だけ
        self.assertEqual(r['trades'], 3)
        self.assertAlmostEqual(r['avg_r'], 1.0)
        self.assertAlmostEqual(r['se'], 2.0 / math.sqrt(3))
        self.assertTrue(math.isnan(v.nse(d.iloc[:1])['se']))

    def test_p2(self):
        syms = OrderedDict([('EURUSD', (100, 0.1)), ('USDJPY', (80, 0.05)), ('EURCHF', (60, -0.1)), ('GBPJPY', (90, 0.2)),
                            ('USDCHF', (70, -0.3)), ('AUDJPY', (29, -1.0))])
        r = v.judge_p2(OrderedDict([('U-D', 0.1), ('U-E', 0.01)]), syms)
        self.assertTrue(r['ok'])
        self.assertAlmostEqual(r['frac'], 0.6)
        self.assertEqual(r['eligible_symbols'], ['EURUSD', 'USDJPY', 'EURCHF', 'GBPJPY', 'USDCHF'])
        self.assertFalse(v.judge_p2(OrderedDict([('U-D', 0.1), ('U-E', 0.0)]), syms)['ok'])
        self.assertFalse(v.judge_p2(OrderedDict([('U-D', 0.1), ('U-E', float('nan'))]), syms)['ok'])   # 取引0回のプール
        self.assertFalse(v.judge_p2(OrderedDict([('U-D', 0.1)]), syms)['ok'])
        self.assertFalse(v.judge_p2(OrderedDict([('U-D', 0.1), ('U-E', 0.1)]),
                                    dict(syms, USDJPY=(80, -0.05)))['ok'])                           # 2/5
        self.assertFalse(v.judge_p2(OrderedDict([('U-D', 0.1), ('U-E', 0.1)]), {'EURUSD': (29, 0.5)})['ok'])

    def test_p4(self):
        seeds = list(np.linspace(-0.1, 0.09, 20))
        mean, p95 = float(np.mean(seeds)), float(np.percentile(seeds, 95))
        r = v.judge_p4(mean + 0.10, seeds)
        self.assertTrue(r['ok'])
        self.assertAlmostEqual(r['naive_p95'], p95)
        self.assertFalse(v.judge_p4(mean + 0.0999, seeds)['ok'])
        self.assertFalse(v.judge_p4(0.1, [0.0] * 18 + [0.2, 0.3])['ok'])
        self.assertTrue(v.judge_p4(0.2, [0.0] * 19 + [1.0])['ok'])
        self.assertFalse(v.judge_p4(0.5, seeds[:-1] + [float('nan')])['ok'])
        self.assertFalse(v.judge_p4(0.5, [])['ok'])

    def test_psr(self):
        """PSR＝Φ( SR̂·√(T−1) ÷ √(1 − γ₃·SR̂ + (γ₄−1)/4·SR̂²) )（SR₀＝0）を、取引のない月を0として手で計算した値と比べる"""
        x = [2, -1, 0, 3, -2, 1, 4, -1]
        months = pd.period_range('2021-01', '2021-08', freq='M')
        rows = []
        for m, val in zip(months, x):
            if val:
                rows += [('komo', 'EURUSD', m.start_time + pd.Timedelta(days=3), val / 2),
                         ('komo', 'USDJPY', m.start_time + pd.Timedelta(days=9), val / 2)]
        b = v.psr_block(trades(rows), ('2021-01', '2021-08'))
        sr, g3, g4 = math.sqrt(1 / 8), 2 / math.sqrt(63), 47 / 27
        want = phi(sr * math.sqrt(7) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
        self.assertAlmostEqual(b['psr'], want, places=12)
        self.assertEqual((b['T'], b['sr0'], b['threshold']), (8, 0.0, 0.95))
        self.assertEqual(b['ok'], want >= 0.95)
        self.assertEqual(list(b['monthly_r'].values()), [float(y) for y in x])
        self.assertAlmostEqual(b['psr'], fe.deflated_sharpe(sr, 8, g3, g4, 0.0), places=14)
        rows = [('komo', 'EURUSD', f'2021-{m:02d}-05', 1.0 + (m % 2) * 0.01) for m in range(1, 13)]
        self.assertTrue(v.psr_block(trades(rows), ('2021-01', '2021-12'))['ok'])        # ほぼ一定のプラス → 0.95 以上
        with self.assertRaises(ValueError):                                             # 期間外の取引は落とさない
            v.psr_block(trades(rows), ('2021-02', '2021-12'))

    def test_naive_choice(self):
        counts = OrderedDict([(0.005, 300.0), (0.0075, 450.0), (0.01, 600.0), (0.0125, 750.0), (0.015, 850.0)])
        s = v.choose_naive_p(counts, 700)
        self.assertEqual(s['p'], 0.0125)
        self.assertTrue(s['within_tol'])
        self.assertEqual(v.choose_naive_p({0.01: 600.0, 0.0125: 800.0}, 700)['p'], 0.01)   # 同じ近さなら小さい p
        self.assertFalse(v.choose_naive_p({0.005: 300.0}, 1000)['within_tol'])

    def test_naive_block_counts_judge_pool_only(self):
        spec = v.make_spec()
        st = {'EURUSD': pd.Timestamp('2022-03-05')}
        c = contact(excluded=[{'symbol': 'EURUSD', 'from': '2021-01-01', 'to': '2021-01-31'}])
        N = OrderedDict()
        for p, n_in, n_out in ((0.01, 3, 40), (0.02, 6, 0)):
            for s in (0, 1):
                rows = [('komo', 'EURUSD', f'2021-0{2 + k % 7}-0{1 + k % 8} 10:00', 0.1 * (s + 1)) for k in range(n_in)]
                rows += [('komo', 'EURUSD', '2016-03-03 10:00', 5.0)] * n_out                 # プールの外
                rows += [('komo', 'EURUSD', '2021-01-10 10:00', 9.0)]                       # 接触の申告で除く
                N[v.naive_name(p, s)] = v.chrono(v.assign(trades(rows), spec, c, st))
        b = v.naive_block(N, 4, [0.01, 0.02], [0, 1])
        self.assertEqual(b['counts'], OrderedDict([(0.01, [3, 3]), (0.02, [6, 6])]))
        self.assertEqual(b['selection']['p'], 0.01)
        self.assertEqual([round(x, 9) for x in b['chosen_seed_avg_r']], [0.1, 0.2])

    def test_gap_counts_fx11(self):
        d = v.assign(trades([('komo', 'USDJPY', '2021-01-04 10:00', -1.0, 1, '2021-01-06', 'GAP_FALLBACK'),
                             ('komo', 'EURCHF', '2021-02-04 10:00', -1.0, 1, '2021-02-06', 'GAP_FALLBACK'),
                             ('komo', 'XAUUSD', '2021-12-23 10:00', 2.0, 1, '2021-12-27 01:00', 'GAP_FALLBACK'),
                             ('komo', 'EURUSD', '2021-03-04 10:00', 1.0, 1, '2021-03-05', 'TRAIL')]),
                     v.make_spec(), NO_CONTACT)
        g = v.gap_block(d, v.SYMBOLS)
        self.assertEqual((g['total'], g['fx']), (3, 2))                               # FX は XAUUSD 以外の11銘柄
        self.assertEqual(g['by_symbol']['USDJPY'], 1)
        self.assertEqual(g['fx_by_year'], OrderedDict([('2021', 2)]))
        self.assertTrue(v.warn_gap(7, 6.46)['fire'])
        self.assertFalse(v.warn_gap(6, 6.46)['fire'])

    def test_ten_month_and_warnings(self):
        rows = [('komo', 'EURUSD', m + pd.Timedelta(days=1, hours=k), 1.0)
                for i, m in enumerate(pd.date_range('2021-01-01', periods=24, freq='MS')) for k in range(i + 1)]
        r = v.ten_month(trades(rows), [v.day_range('2021-01-01', '2022-12-31')])
        sums = [sum(range(i + 1, i + 11)) for i in range(15)]
        self.assertEqual((r['windows'], r['min'], r['max']), (15, min(sums), max(sums)))
        self.assertTrue(v.warn_ten_month(14.9)['fire'])
        self.assertFalse(v.warn_ten_month(15.0)['fire'])
        self.assertTrue(v.warn_long_short(0.1, -0.05)['fire'])
        self.assertFalse(v.warn_long_short(-0.1, -0.05)['fire'])


# ---------------------------------------------------------------- データ源の照合・切断テスト
class TestSourceAndTruncation(unittest.TestCase):
    def test_source_check(self):
        spec = v.make_spec()
        komo = trades([('komo', 'EURUSD', '2018-03-05 10:00', 1.0, 1), ('komo', 'EURUSD', '2018-04-05 10:00', -1.0, -1),
                       ('komo', 'GBPUSD', '2019-04-05 11:00', 2.0, 1), ('komo', 'XAUUSD', '2020-05-14 23:00', -1.0, 1),
                       ('komo', 'EURUSD', '2020-05-15 00:00', 3.0, 1),       # 期間の外
                       ('komo', 'USDJPY', '2018-03-05 10:00', 3.0, 1)])      # 使用済み7銘柄でない
        ref = trades([('komo', 'EURUSD', '2018-03-05 10:00', 1.0, 1), ('komo', 'EURUSD', '2018-04-05 10:00', -1.0, 1),
                      ('komo', 'GBPUSD', '2019-04-05 10:00', 2.0, 1), ('komo', 'XAUUSD', '2020-05-14 23:00', -1.0, 1),
                      ('komo', 'AUDUSD', '2019-01-07 10:00', -1.0, 1)]).drop(columns=['src'])
        r = v.source_check(komo, ref, spec, v.SYMBOLS)
        self.assertEqual((r['komo'], r['oanda'], r['matched']), (4, 5, 2))
        self.assertAlmostEqual(r['rate'], 2 / 5)
        self.assertAlmostEqual(r['rate_vs_komo'], 2 / 4)
        self.assertEqual(r['near_matched'], 3)                                         # ±1時間（GBPUSD）を含む
        self.assertAlmostEqual(r['avg_r_komo'], 0.25)
        self.assertAlmostEqual(r['avg_r_oanda'], 0.0)
        self.assertEqual(r['by_symbol']['EURUSD']['matched'], 1)                       # 方向が違うものは一致にしない
        self.assertEqual(r['by_symbol']['AUDUSD']['komo'], 0)

    def test_truncation_check(self):
        full = trades([('komo', 'EURUSD', '2021-05-03 10:00', 1.0, 1, '2021-05-04 10:00'),
                       ('komo', 'EURUSD', '2021-05-27 10:00', -1.0, 1, '2021-05-31 23:00'),
                       ('komo', 'EURUSD', '2021-05-31 10:00', 2.0, 1, '2021-06-02 10:00')])
        part = full.iloc[:2].copy()
        part.loc[part.index[-1], 'exit_time'] = pd.Timestamp('2021-05-31 23:00')
        info = dict(last=pd.Timestamp('2021-05-31 23:00'))
        r = v.truncation_check(full, part, '2021-06-01', info, 'EURUSD')
        self.assertTrue(r['match'])
        self.assertEqual(r['compared'], 2)
        part.loc[part.index[0], 'pnl_r'] = 1.5
        self.assertFalse(v.truncation_check(full, part, '2021-06-01', info, 'EURUSD')['match'])


# ---------------------------------------------------------------- 記録ファイル（§2・§3.2）
class TestManifest(unittest.TestCase):
    def test_contact(self):
        c, p = v.parse_contact(None, required=True)
        self.assertTrue(p)
        self.assertEqual(v.parse_contact(None, required=False)[1], [])
        c, p = v.parse_contact({'contact': {'asked_on': '2026-11-01', 'excluded': [], 'partial': []}}, required=True)
        self.assertEqual(p, [])
        self.assertIn('asked_on', v.parse_contact({'contact': {'excluded': []}}, required=True)[1][0])
        bad = [{'symbol': 'EURNZD', 'from': '2021-01-01', 'to': '2021-01-02'},
               {'symbol': 'EURUSD', 'from': '2021/01/01', 'to': '2021-01-02'},
               {'symbol': 'EURUSD', 'from': '2021-01-03', 'to': '2021-01-02'},
               {'symbol': 'EURUSD', 'from': '2021-01-03'}]
        c, p = v.parse_contact({'contact': {'asked_on': '2026-11-01', 'excluded': bad}}, required=True)
        self.assertEqual(len(p), 4)
        c = contact(partial=[{'symbol': '*', 'from': '2022-03-05', 'to': '2022-03-05', 'reason': '旧 EA'}])
        e = c['partial'][0]
        self.assertEqual((e['symbol'], e['lo'], e['hi']), ('*', pd.Timestamp('2022-03-05'), pd.Timestamp('2022-03-06')))

    def test_asked_on(self):
        """本番の asked_on は YYYY-MM-DD（日付でなければ止める理由）。指定の日より前・実行した日より後も止める理由"""
        for bad in ('いつか', '2026/11/01', '2026-11-1', '2026-13-01'):
            p = v.parse_contact({'contact': {'asked_on': bad, 'excluded': [], 'partial': []}}, required=True)[1]
            self.assertEqual(len(p), 1, bad)
            self.assertIn('asked_on', p[0])
        self.assertEqual(v.parse_contact({'contact': {'asked_on': 'ドライラン'}}, required=False)[1], [])   # ドライランは問わない
        self.assertEqual(v.asked_on_problems('2026-11-02', '2026-11-01', '2026-11-03'), [])
        self.assertEqual(v.asked_on_problems('2026-11-01', '2026-11-01', '2026-11-01'), [])                # 両端の日を含む
        self.assertIn('より前', v.asked_on_problems('2026-10-31', '2026-11-01', '2026-11-03')[0])
        self.assertIn('より後', v.asked_on_problems('2026-11-04', '2026-11-01', '2026-11-03')[0])
        self.assertEqual(len(v.asked_on_problems('いつか')), 1)
        self.assertEqual(v.asked_on_problems('2026-11-04'), [])

    def test_contact_ud_changes(self):
        """U-D の期間の申告の働き（銘柄×日×種別。excluded が partial に勝つ）を第1段と比べる。書き方（区切り方・"*" か銘柄ごとか）は
        問わない。U-D の外は見ない。第1段の記録は第1段の結果（JSON）から読む"""
        ud = ('2020-05-15', '2022-03-04')
        prev = json.loads(json.dumps(v.clean(contact(excluded=[ent('EURUSD', '2021-01-01', '2021-01-31')],
                                                     partial=[ent('*', '2021-03-01', '2021-03-31')]))))
        same = contact(excluded=[ent('EURUSD', '2021-01-01', '2021-01-15'), ent('EURUSD', '2021-01-16', '2021-01-31')],
                       partial=[ent(s, '2021-03-01', '2021-03-31') for s in v.SYMBOLS]
                       + [ent('EURUSD', '2021-01-10', '2021-01-20'),                 # excluded に含まれる partial は働かない
                          ent('*', '2022-03-05', '2026-10-31'), ent('USDJPY', '2019-01-01', '2020-05-14')])   # U-D の外
        self.assertEqual(v.contact_ud_changes(prev, same, ud), [])
        added = contact(excluded=[ent('EURUSD', '2021-01-01', '2021-01-31'), ent('*', '2021-02-01', '2021-02-28')],
                        partial=[ent('*', '2021-03-01', '2021-03-31')])
        ch = v.contact_ud_changes(prev, added, ud)
        self.assertEqual([c.split('（')[0] for c in ch], v.SYMBOLS)                 # "*" の除外を足した → 12銘柄すべて
        self.assertEqual(ch[0], 'EURUSD（第1段：除外 2021-01-01〜2021-01-31・一部汚れ 2021-03-01〜2021-03-31 → '
                                '第2段：除外 2021-01-01〜2021-02-28・一部汚れ 2021-03-01〜2021-03-31）')
        moved = contact(excluded=[ent('EURUSD', '2021-01-01', '2021-01-31'), ent('GBPUSD', '2021-03-01', '2021-03-31')],
                        partial=[ent('*', '2021-03-01', '2021-03-31')])               # GBPUSD を partial → excluded
        self.assertEqual([c.split('（')[0] for c in v.contact_ud_changes(prev, moved, ud)], ['GBPUSD'])
        dropped = contact(partial=[ent('*', '2021-03-01', '2021-03-31')])           # EURUSD の除外が消えた
        self.assertEqual([c.split('（')[0] for c in v.contact_ud_changes(prev, dropped, ud)], ['EURUSD'])
        edge = contact(excluded=[ent('EURUSD', '2021-01-01', '2021-01-31'), ent('USDJPY', '2022-03-04', '2022-06-30')],
                       partial=[ent('*', '2021-03-01', '2021-03-31'), ent('XAUUSD', '2020-05-01', '2020-05-15')])
        self.assertEqual([c.split('（')[0] for c in v.contact_ud_changes(prev, edge, ud)], ['XAUUSD', 'USDJPY'])  # 両端の日
        self.assertEqual(v.contact_ud_changes({}, contact(partial=[ent('*', '2022-03-05', '2026-10-31')]), ud), [])

    def test_contact_missing(self):
        """第2段の記録は第1段の記録を覆っていること（区切り方は変わってよい。partial → excluded に移すのは、このチェックでは
        よい。U-D の期間は contact_ud_changes が第1段と同じ働きを求めるので、U-D で移すと別の理由で止まる）"""
        prev = contact(excluded=[ent('EURUSD', '2021-01-01', '2021-01-31')],
                       partial=[ent('*', '2021-03-01', '2021-03-31'), ent('USDJPY', '2021-05-01', '2021-05-10')])
        ok = contact(excluded=[ent('EURUSD', '2021-01-01', '2021-01-15'), ent('EURUSD', '2021-01-16', '2021-01-31'),
                               ent('USDJPY', '2021-05-01', '2021-05-10'), ent('GBPUSD', '2023-01-01', '2023-01-31')],
                     partial=[ent('*', '2021-02-01', '2021-04-30')])
        self.assertEqual(v.contact_missing(json.loads(json.dumps(v.clean(prev))), ok), [])   # 第1段の結果（JSON）から読む
        self.assertEqual(v.contact_missing({}, ok), [])
        bad = contact(excluded=[ent('*', '2021-01-01', '2021-01-20')],                       # 1月21日〜31日が抜けた
                      partial=[ent('EURUSD', '2021-03-01', '2021-03-31'), ent('USDJPY', '2021-05-01', '2021-05-10')])
        miss = v.contact_missing(prev, bad)
        self.assertEqual(miss, ['excluded: EURUSD 2021-01-01〜2021-01-31', 'partial: * 2021-03-01〜2021-03-31'])
        moved = contact(partial=[ent('EURUSD', '2021-01-01', '2021-01-31'), ent('*', '2021-03-01', '2021-03-31'),
                                 ent('USDJPY', '2021-05-01', '2021-05-10')])                  # excluded → partial は不可
        self.assertEqual(v.contact_missing(prev, moved), ['excluded: EURUSD 2021-01-01〜2021-01-31'])

    def test_stage2_manifest(self):
        good = {'broker': {'name': 'B', 'server': 'S', 'account_type': 'demo', 'exported_on': '2026-11-02'},
                'symbol_map': {s: f'{s}.a' for s in v.SYMBOLS}}
        good['symbol_map']['EURCHF'] = {'broker_symbol': None, 'reason': 'ない'}
        b, m, p = v.parse_stage2_manifest(good, required=True)
        self.assertEqual(p, [])
        self.assertEqual(m['EURUSD']['broker_symbol'], 'EURUSD.a')
        self.assertIsNone(m['EURCHF']['broker_symbol'])
        bad = json.loads(json.dumps(good))
        del bad['symbol_map']['USDJPY']
        bad['symbol_map']['GBPJPY'] = None                          # 理由のない「対応なし」
        bad['symbol_map']['EURNZD'] = 'EURNZD'
        bad['broker']['server'] = ''
        self.assertEqual(len(v.parse_stage2_manifest(bad, required=True)[2]), 4)
        self.assertEqual(v.parse_stage2_manifest({}, required=False)[2], [])


# ---------------------------------------------------------------- 本番の実行前の確認（何も計算しないうちに止める）
class TestProductionGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='v11_guard_')
        self.komo = os.path.join(self.tmp, 'komo')
        os.makedirs(self.komo)
        for s in v.SYMBOLS[:3]:                                     # 時刻の列だけの小さなファイル（12銘柄そろっていない）
            with open(os.path.join(self.komo, f'{s}h1.csv'), 'w') as f:
                f.write('Date,open,high,low,close,tick_volume\n2021-03-01 00:00:00,1000,1000,1000,1000,1\n')
        self.man = {'contact': {'asked_on': '2026-11-01', 'excluded': [], 'partial': []}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run1(self, **kw):
        args = dict(komo_dir=self.komo, out_dir=os.path.join(self.tmp, 'out'), manifest=self.man, workers=1,
                    log=lambda s: None)
        args.update(kw)
        with mock.patch.object(v, 'Runner') as rn:
            with self.assertRaises(SystemExit) as cm:
                v.run_stage1(**args)
            rn.assert_not_called()
        return str(cm.exception)

    def test_stage1_stops_before_computing(self):
        msg = self.run1(require_clean_git=False)
        self.assertIn('komo135 のファイルがない銘柄', msg)
        self.assertIn('行数', msg)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'out', 'stage1_run.log')))
        self.assertIn('contact', self.run1(manifest={'broker': {}}, require_clean_git=False))
        with mock.patch.object(v, 'prereg_stage1_contact', return_value=(None, ['§2 の確認の記録がない'])):
            self.assertIn('§2 の確認の記録がない', self.run1(manifest=None, require_clean_git=False))
        c = OrderedDict(asked_on='2026-11-01', summary='見ていない', excluded=[], partial=[])
        with mock.patch.object(v, 'prereg_stage1_contact', return_value=(c, [])):
            self.assertNotIn('記録', self.run1(manifest=None, require_clean_git=False))
        dirty = dict(v.git_state(), eval_files_dirty=['fusion/v11_eval.py'])
        with mock.patch.object(v, 'git_state', return_value=dirty):
            self.assertIn('fusion/v11_eval.py', self.run1())

    def test_stage1_contact_from_prereg(self):
        """第1段で記録ファイルを渡さないときは、事前登録 §2 の「第1段の前の確認の結果（日付）」を使う（除く銘柄×期間がないときだけ）"""
        p = os.path.join(self.tmp, 'prereg.md')

        def write(body):
            with open(p, 'w', encoding='utf-8') as f:
                f.write('## 2. 接触の申告\n\n- 確認の方法\n' + body + '- 「新しい」とは…\n\n## 3. データ\n')
        write('- **第1段の前の確認の結果（2026-11-01）**：利用者の回答は「見ていない」。\n'
              '  よって U-D は、除外も「一部汚れ」の記録もなしに、未接触として判定に使う。\n')
        c, problems = v.prereg_stage1_contact(p)
        self.assertEqual(problems, [])
        self.assertEqual((c['asked_on'], c['excluded'], c['partial']), ('2026-11-01', [], []))
        self.assertIn('見ていない', c['summary'])
        self.assertNotIn('新しい', c['summary'])                    # 次の項目は含めない
        write('- **第1段の前の確認の結果（2026-11-01）**：EURUSD の 2021 年を EA のパネルで見た。\n')
        self.assertIsNone(v.prereg_stage1_contact(p)[0])
        self.assertIn('--manifest', v.prereg_stage1_contact(p)[1][0])
        write('')
        self.assertIn('記録がない', v.prereg_stage1_contact(p)[1][0])
        self.assertIn('読めない', v.prereg_stage1_contact(os.path.join(self.tmp, 'none.md'))[1][0])
        c, problems = v.prereg_stage1_contact()                    # いまの事前登録（記録があれば日付を読む）
        if c is not None:
            self.assertRegex(c['asked_on'], r'^\d{4}-\d{2}-\d{2}$')

    def test_results_are_not_overwritten(self):
        out = os.path.join(self.tmp, 'out')
        os.makedirs(out)
        open(os.path.join(out, 'stage1_results.json'), 'w').close()
        self.assertIn('1回だけ', self.run1(require_clean_git=False))

    def test_dry_run_takes_no_new_data(self):
        self.assertIn('開発データだけ', self.run1(dry_run=True, dev_dir=self.tmp))
        with self.assertRaises(SystemExit):
            v.run_stage2(komo_dir=self.komo, out_dir=os.path.join(self.tmp, 'o2'), dry_run=True, dev_dir=self.tmp,
                         log=lambda s: None)

    def test_stage2_needs_stage1(self):
        with self.assertRaises(SystemExit) as cm:
            v.run_stage2(komo_dir=self.komo, mt5_dir=self.tmp, manifest=self.man, out_dir=os.path.join(self.tmp, 'o2'),
                         log=lambda s: None)
        self.assertIn('--stage1-dir', str(cm.exception))
        s1 = os.path.join(self.tmp, 's1')
        os.makedirs(s1)
        tf = os.path.join(s1, 'stage1_trades.csv.gz')
        with open(tf, 'wb') as f:
            f.write(b'x')
        js = {'meta': {'stage': 1, 'dry_run': False}, 'stop': {'stop': True, 'verdict': '不合格（第1段で打ち切り）'},
              'trades_file': {'file': 'stage1_trades.csv.gz', 'sha256': v.sha256_of(tf)}}
        with open(os.path.join(s1, 'stage1_results.json'), 'w') as f:
            json.dump(js, f)
        _, _, p = v.load_stage1(s1, dry=False)
        self.assertEqual(len(p), 1)
        self.assertIn('打ち切り', p[0])
        with open(tf, 'wb') as f:
            f.write(b'y')
        _, _, p = v.load_stage1(s1, dry=False)
        self.assertTrue(any('SHA-256' in x for x in p))
        self.assertTrue(any('混ざって' in x for x in v.load_stage1(s1, dry=True)[2]))

    def test_prereg_frozen_and_deadline(self):
        """本番は、事前登録に「まだ凍結していない」の注記が残っていれば止める。第2段は期限（2027-02-01）を過ぎたら止める"""
        p = os.path.join(self.tmp, 'prereg.md')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('# 事前登録\n\n> **2026-11-01 時点：作業を一時停止中。この版はまだ凍結していない**\n')
        self.assertEqual(len(v.prereg_problems(p)), 1)
        with open(p, 'w', encoding='utf-8') as f:
            f.write('# 事前登録\n\n本文\n')
        self.assertEqual(v.prereg_problems(p), [])
        self.assertEqual(len(v.prereg_problems(os.path.join(self.tmp, 'none.md'))), 1)
        self.assertEqual(v.deadline_problems('2027-02-01'), [])
        self.assertEqual(v.deadline_problems(pd.Timestamp('2027-02-01 23:59')), [])
        self.assertEqual(len(v.deadline_problems('2027-02-02')), 1)
        with mock.patch.object(v, 'prereg_problems', return_value=['未凍結']):
            self.assertIn('未凍結', self.run1())
        msg = self.run1(require_clean_git=False)                    # テスト用の設定では git と凍結の確認を省く
        self.assertNotIn('凍結', msg)

    def test_code_changes_since(self):
        head = v.git_state()['commit']
        self.assertEqual(v.code_changes_since(head), [])
        self.assertIsNone(v.code_changes_since(None))
        self.assertIsNone(v.code_changes_since('0' * 40))
        draft = v.code_changes_since('ce7f5a4')                     # 事前登録の草稿のコミット（その後に事前登録を直した）
        if draft is not None:
            self.assertIn(v.PREREG, draft)

    def fake_stage1(self, commit='c' * 40, excluded=(), partial=(), run_date='2026-11-01', ref_sha=None):
        s1 = os.path.join(self.tmp, 's1')
        os.makedirs(s1, exist_ok=True)
        tf = os.path.join(s1, 'stage1_trades.csv.gz')
        with open(tf, 'wb') as f:
            f.write(b'x')
        js = {'meta': {'stage': 1, 'dry_run': False, 'git': {'commit': commit}, 'run_date': run_date, 'tz': v.tz_info(),
                       'contact': {'asked_on': '2026-11-01', 'excluded': list(excluded), 'partial': list(partial)}},
              'stop': {'stop': False, 'verdict': '継続'}, 'trades_file': {'file': 'stage1_trades.csv.gz', 'sha256': v.sha256_of(tf)}}
        if ref_sha:
            js['source_check'] = {'reference': {'sha256': ref_sha}}
        with open(os.path.join(s1, 'stage1_results.json'), 'w') as f:
            json.dump(js, f)
        return s1, js

    def stage2_args(self, s1, **kw):
        args = dict(komo_dir=self.komo, mt5_dir=self.tmp, manifest=self.man, out_dir=os.path.join(self.tmp, 'o2'),
                    stage1_dir=s1, log=lambda s: None, require_clean_git=False, today='2026-11-02')
        args.update(kw)
        return args

    def run2(self, **kw):
        """本番の第2段を走らせ、何も計算しないうちに止まることを確かめて、止めた理由を返す"""
        with mock.patch.object(v, 'Runner') as rn:
            with self.assertRaises(SystemExit) as cm:
                v.run_stage2(**kw)
            rn.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(kw['out_dir'], 'stage2_run.log')))
        return str(cm.exception)

    def test_stage1_link(self):
        """§2・§7.2: 第1段の接触の申告が第2段の記録で覆われているか・U-D の期間の申告が同じか。評価に使うファイルが
        第1段のコミットから変わっていないか（事前登録に書き足したときは、戻すように言う）"""
        e = ent('EURUSD', '2021-01-01', '2021-01-31', 'EA のパネル')
        _, js = self.fake_stage1(excluded=[e])
        g, spec = {'commit': 'd' * 40}, v.make_spec()
        with mock.patch.object(v, 'code_changes_since', return_value=[]):
            rec, cp, gp = v.stage1_link(js, contact(excluded=[e]), g, None, spec)
        self.assertEqual((cp, gp, rec['same_commit'], rec['eval_files_changed'], rec['contact_ud_changes']),
                         ([], [], False, [], []))
        self.assertTrue(rec['tz']['same'])
        with mock.patch.object(v, 'code_changes_since', return_value=['fusion/strategy.py']):
            rec, cp, gp = v.stage1_link(js, contact(), g, None, spec)
            self.assertEqual(len(cp), 2)                            # 第1段の記録が消えた（覆われていない・U-D の申告が違う）
            self.assertIn('覆われていない', cp[0])
            self.assertIn('U-D の期間', cp[1])
            self.assertIn('--code-fix-reason', gp[0])
            self.assertNotIn('事前登録を第1段のコミットの版に戻して', gp[0])
            rec, _, gp = v.stage1_link(js, contact(excluded=[e]), g, '読み込みの例外を直した', spec)
            self.assertEqual((gp, rec['code_fix_reason']), ([], '読み込みの例外を直した'))
        with mock.patch.object(v, 'code_changes_since', return_value=[v.PREREG]):    # 凍結後の事前登録に書き足した
            self.assertIn('事前登録を第1段のコミットの版に戻して', v.stage1_link(js, contact(excluded=[e]), g, None, spec)[2][0])
        with mock.patch.object(v, 'code_changes_since', return_value=None):
            self.assertIn('git', v.stage1_link(js, contact(excluded=[e]), g, None, spec)[2][0])
        with mock.patch.object(v, 'code_changes_since', side_effect=AssertionError('呼ばない')):
            rec, _, gp = v.stage1_link(js, contact(excluded=[e]), {'commit': 'c' * 40}, None, spec)   # 同じコミット
        self.assertEqual((rec['same_commit'], gp), (True, []))
        js['meta']['tz'] = dict(js['meta']['tz'], version='1999z')  # tz の版が違う → 記録する（止めない）
        rec, cp, _ = v.stage1_link(js, contact(excluded=[e]), {'commit': 'c' * 40}, None, spec)
        self.assertEqual((rec['tz']['same'], cp), (False, []))

    def test_stage2_asked_on_after_stage1(self):
        """§2・§3.2: 第2段の前の確認の日（asked_on）は、第1段の実行日以後・第2段の実行日以前（本番。run_date を渡したとき）"""
        _, js = self.fake_stage1(run_date='2026-11-03')
        g, spec = {'commit': 'c' * 40}, v.make_spec()
        for asked, n in (('2026-11-03', 0), ('2026-11-10', 0), ('2026-11-01', 1), ('2026-11-11', 1)):
            self.assertEqual(len(v.stage1_link(js, contact(asked_on=asked), g, None, spec, run_date='2026-11-10')[1]), n, asked)
        self.assertEqual(v.stage1_link(js, contact(asked_on='2026-11-01'), g, None, spec)[1], [])   # ドライラン（run_date なし）
        del js['meta']['run_date']
        cp = v.stage1_link(js, contact(asked_on='2026-11-05'), g, None, spec, run_date='2026-11-10')[1]
        self.assertTrue(any('run_date' in x for x in cp))
        s1, _ = self.fake_stage1(run_date='2026-11-03')
        msg = self.run2(**self.stage2_args(s1))                     # self.man の asked_on は 2026-11-01（第1段より前）
        self.assertIn('第2段の contact.asked_on', msg)

    def test_stage2_stops_when_ud_contact_changes(self):
        """F1・R1: 第1段の記録（除外なし）に、第2段で U-D の期間の除外を足すと、本番は何も計算しないうちに止まる
        （第1段の記録を正とする）。U-E の期間だけを書き足すのはよい"""
        s1, _ = self.fake_stage1()
        for extra in ({'excluded': [ent('*', '2021-01-01', '2021-03-31', '後から思い出した')]},
                      {'partial': [ent('EURUSD', '2020-05-15', '2026-10-31', '覚えていない')]}):
            man = {'contact': dict({'asked_on': '2026-11-02', 'excluded': [], 'partial': []}, **extra)}
            msg = self.run2(**self.stage2_args(s1, manifest=man))
            self.assertIn('U-D の期間 2020-05-15〜2022-03-04 の申告が第1段の記録と違う', msg)
            self.assertIn('第1段の記録を正とする', msg)
        man = {'contact': {'asked_on': '2026-11-02', 'excluded': [ent('*', '2022-03-05', '2022-03-31')],
                           'partial': [ent('EURUSD', '2023-01-01', '2026-10-31')]}}
        msg = self.run2(**self.stage2_args(s1, manifest=man))       # ほかの理由（ファイルがそろっていない）で止まる
        self.assertNotIn('U-D の期間', msg)
        self.assertNotIn('asked_on', msg)

    def test_stage2_stops_on_stage1_link(self):
        """本番の第2段: 第1段の記録が消えた・コードが変わった（理由なし）・期限切れなら、何も計算しないうちに止める"""
        e = ent('EURUSD', '2021-01-01', '2021-01-31', 'EA のパネル')
        s1, _ = self.fake_stage1(excluded=[e])
        with mock.patch.object(v, 'code_changes_since', return_value=['fusion/broker.py']), \
                mock.patch.object(v, 'git_problems', return_value=[]), mock.patch.object(v, 'prereg_problems', return_value=[]):
            msg = self.run2(**self.stage2_args(s1, require_clean_git=True, today='2027-02-02'))
        for word in ('覆われていない', 'U-D の期間', 'fusion/broker.py', '--code-fix-reason', '期限'):
            self.assertIn(word, msg)
        self.assertNotIn('--stage1-dir で第1段の出力フォルダを指す', msg)   # --stage1-dir の第1段は読めている

    def test_golden_check(self):
        """§7.2: 開発データのゴールデンの確認（子プロセスの unittest の出力を読む）。省かれた・失敗した・データがないなら ok にしない"""
        def fake(text, code=0):
            return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout='', stderr=text)
        d = os.path.join(self.tmp, 'dev')
        os.makedirs(d)
        open(os.path.join(d, 'EURUSD_H1.csv'), 'w').close()
        ok = ('test_backtesting_eurusd_2017 (fusion.tests.test_strategy.TestGolden.test_backtesting_eurusd_2017) ... ok\n'
              'test_oanda_eurusd_is (fusion.tests.test_strategy.TestGolden.test_oanda_eurusd_is) ... ok\n\n'
              + '-' * 70 + '\nRan 2 tests in 3.073s\n\nOK\n')
        r = v.golden_check(d, run=fake(ok))
        self.assertTrue(r['ok'])
        self.assertEqual(dict(r['tests']), {'test_backtesting_eurusd_2017': 'ok', 'test_oanda_eurusd_is': 'ok'})
        self.assertIn('Ran 2 tests', r['summary'])
        skipped = ok.replace('test_oanda_eurusd_is) ... ok', "test_oanda_eurusd_is) ... skipped 'FUSION_DATA_DIR がない'")
        self.assertIn('skipped', v.golden_check(d, run=fake(skipped))['reason'])
        self.assertIn('失敗', v.golden_check(d, run=fake(ok.replace('\nOK\n', '\nFAILED (failures=1)\n'), 1))['reason'])
        for missing in (None, self.tmp):                            # 開発データ（EURUSD_H1.csv）がない
            self.assertIn('開発データ', v.golden_check(missing, run=fake(ok))['reason'])
        if DEV_DIR and os.path.exists(os.path.join(DEV_DIR, 'EURUSD_H1.csv')):   # 本物の子プロセス
            r = v.golden_check(DEV_DIR)
            self.assertTrue(r['ok'], r)
            self.assertEqual(r['tests'][v.GOLDEN_NEED], 'ok')

    def test_stage2_code_fix_needs_golden(self):
        """§7.2: 第1段の後に評価に使うファイルを直したら（--code-fix-reason）、本番はゴールデンが一致することを確かめてから走らせる"""
        s1, _ = self.fake_stage1()
        bad = OrderedDict(ok=False, test=v.GOLDEN_TEST, tests=OrderedDict(), reason='test_oanda_eurusd_is が通っていない（skipped）')
        good = OrderedDict(ok=True, test=v.GOLDEN_TEST, tests=OrderedDict(test_oanda_eurusd_is='ok'))
        args = self.stage2_args(s1, require_clean_git=True, code_fix_reason='読み込みの例外を直した', golden_dir='/dev/data')
        calls = []
        with mock.patch.object(v, 'code_changes_since', return_value=['fusion/strategy.py']), \
                mock.patch.object(v, 'git_problems', return_value=[]), mock.patch.object(v, 'prereg_problems', return_value=[]):
            self.assertIn('ゴールデン', self.run2(golden=lambda d: calls.append(d) or bad, **args))
            self.assertNotIn('ゴールデン', self.run2(golden=lambda d: calls.append(d) or good, **args))   # ほかの理由で止まる
        self.assertEqual(calls, ['/dev/data', '/dev/data'])
        with mock.patch.object(v, 'code_changes_since', return_value=[]):        # 変わっていなければ確かめない
            self.run2(golden=lambda d: calls.append(d) or bad, **args)
        self.assertEqual(len(calls), 2)

    def test_stage2_reference_must_match_stage1(self):
        """データ源の照合に使う v1.0 の取引一覧（fusion/results/final_eval_trades_main.csv.gz）が第1段と違えば止める"""
        s1, _ = self.fake_stage1(ref_sha='0' * 64)
        self.assertIn('v1.0 の取引一覧の SHA-256 が第1段と違う', self.run2(**self.stage2_args(s1)))
        s1, _ = self.fake_stage1(ref_sha=v.sha256_of(v.REF_TRADES))
        self.assertNotIn('v1.0 の取引一覧', self.run2(**self.stage2_args(s1)))

    def test_stage1_manifest_must_agree_with_prereg(self):
        """第1段で記録ファイルを渡すときは、事前登録 §2 の第1段の前の確認の結果（除外なし）と矛盾しないこと。asked_on は日付で、
        実行した日より後でないこと"""
        c = OrderedDict(asked_on='2026-11-01', summary='見ていない', excluded=[], partial=[])
        with_ex = {'contact': {'asked_on': '2026-11-01', 'excluded': [ent('EURUSD', '2021-01-01', '2021-01-31')], 'partial': []}}
        with mock.patch.object(v, 'prereg_stage1_contact', return_value=(c, [])):
            self.assertIn('事前登録と矛盾', self.run1(manifest=with_ex, require_clean_git=False))
            self.assertNotIn('事前登録と矛盾', self.run1(require_clean_git=False))       # self.man は除外なし
            self.assertIn('asked_on', self.run1(manifest={'contact': {'asked_on': 'いつか'}}, require_clean_git=False))
            self.assertIn('より後', self.run1(require_clean_git=False, today='2026-10-31'))
            self.assertIn('より後', self.run1(manifest=None, require_clean_git=False, today='2026-10-31'))
        with mock.patch.object(v, 'prereg_stage1_contact', return_value=(None, ['除く銘柄×期間は --manifest で渡す'])):
            self.assertNotIn('事前登録と矛盾', self.run1(manifest=with_ex, require_clean_git=False))   # 記録ファイルが正
        pc, _ = v.prereg_stage1_contact()
        if pc is not None:                                          # いまの事前登録の記録（除外なし）
            self.assertEqual(v.stage1_manifest_problems(contact()), [])
            self.assertEqual(len(v.stage1_manifest_problems(contact(partial=[ent('*', '2020-05-15', '2022-03-04')]))), 1)

    def test_dry_and_production_outputs_kept_apart(self):
        """ドライランは本番の結果・ログがあるフォルダに書かない（上書きしない）。本番はドライランの出力があるフォルダで走らない"""
        out = os.path.join(self.tmp, 'prod')
        os.makedirs(out)
        with open(os.path.join(out, 'stage1_results.json'), 'w') as f:
            json.dump({'meta': {'stage': 1, 'dry_run': False}}, f)
        dry = dict(out_dir=out, dry_run=True, dev_dir=self.tmp, komo_dir=None, manifest=None)
        self.assertIn('本番の出力（stage1_results.json）', self.run1(**dry))
        with open(os.path.join(out, 'stage1_results.json')) as f:
            self.assertFalse(json.load(f)['meta']['dry_run'])       # 上書きしていない
        self.assertFalse(os.path.exists(os.path.join(out, 'dry_input')))
        os.remove(os.path.join(out, 'stage1_results.json'))
        with open(os.path.join(out, 'stage1_run.log'), 'w', encoding='utf-8') as f:
            f.write('=== 実行 第1回 ===\n本番のログ\n')                # 結果のファイルができる前に失敗した本番のログ
        self.assertIn('stage1_run.log', self.run1(**dry))
        msg = self.run2(out_dir=out, dry_run=True, dev_dir=self.tmp, log=lambda s: None)
        self.assertIn('本番の出力', msg)
        with open(os.path.join(out, 'stage1_run.log'), encoding='utf-8') as f:
            self.assertEqual(f.readline(), '=== 実行 第1回 ===\n')
        dout = os.path.join(self.tmp, 'dry')
        os.makedirs(os.path.join(dout, 'dry_input'))
        with open(os.path.join(dout, 'stage1_run.log'), 'w', encoding='utf-8') as f:
            f.write('=== ドライラン（数値は無意味） ===\n')
        self.assertIn('ドライランの出力', self.run1(out_dir=dout, require_clean_git=False))
        self.assertIn('ドライランの出力', self.run2(**self.stage2_args(None, out_dir=dout)))
        self.assertEqual(v.out_contents(dout), ([], ['stage1_run.log', 'dry_input/']))
        with open(os.path.join(dout, 'stage2_results.json'), 'w') as f:
            f.write('{読めない')                                      # 読めない結果は本番のものとみなす（上書きしない）
        self.assertEqual(v.out_contents(dout)[0], ['stage2_results.json'])

    def test_cli(self):
        """CLI: 第2段の --stage1-dir の既定は --out（run_stage2 に None を渡し、run_stage2 が --out を使う）。
        --dev-dir の既定は FUSION_DATA_DIR で、ドライランのときだけ使う"""
        with mock.patch.object(v, 'run_stage2') as r2, mock.patch.object(v, 'run_stage1') as r1, \
                mock.patch.dict(os.environ, {'FUSION_DATA_DIR': '/dev/data'}):
            v.main(['stage2', '--komo-dir', 'K', '--mt5-dir', 'M', '--manifest', 'J', '--out', 'O'])
            kw = r2.call_args.kwargs
            self.assertEqual((kw['stage1_dir'], kw['out_dir'], kw['dev_dir'], kw['code_fix_reason'], kw['workers']),
                             (None, 'O', None, None, 4))
            self.assertEqual(kw['golden_dir'], '/dev/data')          # 本番は開発データを評価に使わず、ゴールデンの確認にだけ使う
            v.main(['stage2', '--dry-run', '--out', 'O', '--code-fix-reason', 'R', '--stage1-dir', 'S', '--workers', '2'])
            kw = r2.call_args.kwargs
            self.assertEqual((kw['stage1_dir'], kw['dev_dir'], kw['code_fix_reason'], kw['dry_run'], kw['workers']),
                             ('S', '/dev/data', 'R', True, 2))
            self.assertIsNone(kw['golden_dir'])
            v.main(['stage1', '--komo-dir', 'K', '--manifest', 'J', '--out', 'O'])
            kw = r1.call_args.kwargs
            self.assertEqual((kw['komo_dir'], kw['manifest'], kw['out_dir'], kw['dev_dir']), ('K', 'J', 'O', None))
        for word in ('"contact"', '"symbol_map"', '"broker"', 'excluded', 'partial'):
            self.assertIn(word, v.MANIFEST_HELP)

    def test_rerun_log(self):
        """結果のファイルができる前に失敗した実行は、理由を書けば走らせ直せる（回数と理由をログに残す）"""
        p = os.path.join(self.tmp, 'stage1_run.log')
        a = v.RunLog(lambda s: None)
        a('前の実行')
        a.open(p, dry=False, rerun_reason=None)
        a.close()
        with self.assertRaises(SystemExit):
            v.RunLog(lambda s: None).open(p, dry=False, rerun_reason=None)
        b = v.RunLog(lambda s: None)
        b.open(p, dry=False, rerun_reason='読み込みの例外を直した')
        b('2回目')
        b.close()
        with open(p, encoding='utf-8') as f:
            text = f.read()
        self.assertIn('=== 実行 第1回 ===', text)
        self.assertIn('=== 実行 第2回（走らせ直し。理由: 読み込みの例外を直した） ===', text)
        self.assertLess(text.index('前の実行'), text.index('2回目'))


# ---------------------------------------------------------------- 全体の通し（開発データの中の仮のプール。数値は無意味）
def e2e_spec():
    spec = v.make_spec(dry_run=True)
    alias = OrderedDict([('EURUSD', 'EURUSD'), ('XAUUSD', 'XAUUSD'), ('USDJPY', 'EURJPY'), ('EURCHF', 'EURUSD'),
                         ('USDCHF', 'GBPUSD')])
    spec.update(symbols=[s for s in v.SYMBOLS if s in alias], dry_alias=alias,
                komo_clip=('2016-01-01', '2016-12-31'), ux=('2016-03-01', '2016-06-30'),
                ux_from=OrderedDict(EURCHF='2016-05-01'), src_check=('2016-01-01', '2016-06-30'),
                ud=('2016-07-01', '2016-12-30'), cut=('EURUSD', '2016-10-03'),
                mt5_clip=('2016-08-01', '2017-03-31'), ue_late='2016-08-01', ue_drop='2016-11-01',
                ue=('2016-11-01', '2017-03-31'), ue_after=('2017-02-01', '2017-03-31'), psr_months=('2016-07', '2017-03'))
    return spec


class TestEndToEnd(unittest.TestCase):
    """ドライランの通り道: 第1段 → 第2段（第1段と照合）。同じ入力から同じ出力（1プロセスと2プロセスでも同じ）"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='v11_e2e_')
        cls.dev = make_dev_dir(os.path.join(cls.tmp, 'dev'), start='2016-01-01', end='2017-04-01')
        cls.spec = e2e_spec()
        cls.git = mock.patch.object(v, 'git_state', return_value=v.git_state())   # テストの途中のコミットで出力が変わらないように
        cls.git.start()
        cls.addClassCleanup(cls.git.stop)
        cls.s1 = os.path.join(cls.tmp, 's1a')
        cls.r1 = v.run_stage1(out_dir=cls.s1, workers=1, dry_run=True, dev_dir=cls.dev, spec=cls.spec, log=lambda s: None)
        cls.s2 = os.path.join(cls.tmp, 's2a')
        cls.r2 = v.run_stage2(out_dir=cls.s2, stage1_dir=cls.s1, workers=1, dry_run=True, dev_dir=cls.dev, spec=cls.spec,
                              naive_p=[0.02, 0.05], naive_seeds=[0, 1], log=lambda s: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def same_files(self, a, b, names):
        for n in names:
            with open(os.path.join(a, n), 'rb') as x, open(os.path.join(b, n), 'rb') as y:
                self.assertEqual(x.read(), y.read(), n)

    def test_stage1_outputs(self):
        r = self.r1
        self.assertEqual(set(r), {'meta', 'configs', 'stop', 'source_check', 'truncation', 'trades_file'})
        for c in v.CONFIGS:                                         # 第1段は取引数・平均R・標準誤差だけ（取引ごとの一覧は出さない）
            for k, x in r['configs'][c].items():
                self.assertEqual(list(x), ['trades', 'avg_r', 'se'], (c, k))
        self.assertTrue(r['meta']['dry_run'])
        self.assertIsNone(r['meta']['run_date'])                    # ドライランは実行日を書かない（出力を日によらず同じにする）
        self.assertEqual(r['meta']['tz'], v.tz_info())
        self.assertTrue(r['truncation']['match'])
        self.assertGreater(r['truncation']['compared'], 0)
        self.assertGreater(r['source_check']['komo'], 0)
        self.assertEqual(r['source_check']['symbols'], ['EURUSD', 'XAUUSD'])
        with open(os.path.join(self.s1, 'stage1_results.json'), encoding='utf-8') as f:
            text = f.read()
        for word in ('psr', 'naive', 'P1', 'ci95', 't_stat'):        # P1〜P6・素朴・PSR は計算もしない
            self.assertNotIn(word, text)
        with open(os.path.join(self.s1, 'stage1_report.md'), encoding='utf-8') as f:
            rep = f.read()
        self.assertTrue(rep.startswith('# 【ドライラン：数値は無意味】'))
        self.assertIn('第2段の前にはこれを集計しない', rep)
        tr = pd.read_csv(os.path.join(self.s1, 'stage1_trades.csv.gz'), keep_default_na=False)
        self.assertEqual(len(tr), r['trades_file']['rows'])
        self.assertEqual(r['trades_file']['sha256'], v.sha256_of(os.path.join(self.s1, 'stage1_trades.csv.gz')))
        self.assertEqual(set(tr['config']), set(v.CONFIGS))
        ud = tr[(tr['config'] == v.MAIN) & (tr['pool'] == 'U-D') & (tr['contact'] != 'excluded')]
        self.assertEqual(len(ud), r['stop']['trades'])
        self.assertAlmostEqual(ud['pnl_r'].mean(), r['stop']['avg_r'], places=12)
        self.assertEqual(r['stop']['stop'], not r['stop']['avg_r'] > 0)
        self.assertTrue(set(tr.loc[tr['pool'] == 'U-X', 'symbol']) <= set(v.NEW))
        self.assertEqual(r['configs'][v.MAIN]['U-X_incl']['trades'],
                         r['configs'][v.MAIN]['U-X']['trades'] + r['configs'][v.MAIN]['U-X_chf_excluded']['trades'])

    def test_stage1_deterministic(self):
        out = os.path.join(self.tmp, 's1b')
        v.run_stage1(out_dir=out, workers=1, dry_run=True, dev_dir=self.dev, spec=self.spec, log=lambda s: None)
        self.same_files(self.s1, out, ['stage1_results.json', 'stage1_trades.csv.gz', 'stage1_report.md'])

    def test_stage2_outputs(self):
        r = self.r2
        m = r['meta']
        self.assertEqual(m['clock']['kind'], 'athens')
        self.assertNotIn('XAUUSD', m['clock']['per_symbol'])      # 時刻の判定は FX の銘柄だけ
        self.assertTrue(m['stage1_consistency']['all_match'])
        self.assertFalse(m['ue_windows']['ok'])                     # ドライランは最低限の量に届かなくても続ける
        for k in v.PS + ['pass', 'warnings', 'label']:
            self.assertIn(k, r['verdict'])
        self.assertEqual(r['psr']['T'], 9)
        nv = r['naive']
        self.assertIn(nv['selection']['p'], (0.02, 0.05))
        self.assertEqual(nv['selection']['target'], r['configs'][v.MAIN]['judge']['trades'])
        tr = pd.read_csv(os.path.join(self.s2, 'stage2_trades.csv.gz'), keep_default_na=False)
        j = tr[(tr['config'] == v.MAIN) & tr['pool'].isin(['U-D', 'U-E']) & (tr['contact'] != 'excluded')]
        self.assertEqual(len(j), r['configs'][v.MAIN]['judge']['trades'])
        self.assertAlmostEqual(j['pnl_r'].sum(), r['configs'][v.MAIN]['judge']['total_r'], places=9)
        self.assertTrue(set(tr.loc[tr['pool'] == 'U-E', 'src']) <= {'mt5'})
        self.assertTrue(set(tr.loc[tr['pool'] == 'U-D', 'src']) <= {'komo'})
        ue = tr[tr['pool'] == 'U-E']
        self.assertGreaterEqual(pd.to_datetime(ue['entry_time']).min(), pd.Timestamp('2016-11-01'))
        with open(os.path.join(self.s2, 'dry_input', 'manifest.json'), encoding='utf-8') as f:
            c, _ = v.parse_contact(json.load(f), required=True)
        et = pd.to_datetime(tr['entry_time'])
        for kind in ('partial', 'excluded'):                        # 印は記録の期間から計算し直したものと同じ
            want = np.zeros(len(tr), dtype=bool)
            for e in c[kind]:
                want |= (tr['pool'].isin(['U-D', 'U-E']) & tr['symbol'].isin(v.SYMBOLS if e['symbol'] == '*' else [e['symbol']])
                         & (et >= e['lo']) & (et < e['hi'])).to_numpy()
            if kind == 'partial':
                want_p = want
            else:
                self.assertEqual((tr['contact'] == 'excluded').tolist(), want.tolist())
                self.assertEqual((tr['contact'] == 'partial').tolist(), (want_p & ~want).tolist())
        nt = pd.read_csv(os.path.join(self.s2, 'stage2_naive_trades.csv.gz'), keep_default_na=False)
        self.assertEqual(sorted(set(nt['config'])), sorted(v.naive_name(p, s) for p in (0.02, 0.05) for s in (0, 1)))
        net = pd.to_datetime(nt['entry_time'])                     # 素朴ベースラインは判定プールの始まり以降だけを残す
        self.assertGreaterEqual(net[nt['src'] == 'komo'].min(), pd.Timestamp(self.spec['ud'][0]))
        self.assertGreaterEqual(net[nt['src'] == 'mt5'].min(), pd.Timestamp(self.spec['ue'][0]))
        self.assertGreater(int(nt['pool'].isin(['U-D', 'U-E']).sum()), 0)
        self.assertTrue(m['stage1_consistency']['gate_ok'])
        self.assertTrue(m['stage1_consistency']['contact_ok'])
        j = m['stage1_consistency']['ud_judged']                    # 第1段に出した U-D の v1.1 と、第2段の U-D（判定に使う取引）
        self.assertTrue(j['match'])
        self.assertEqual((j['stage1'], j['stage2'], j['stage2_trades']), (self.r1['stop']['trades'],) * 3)
        self.assertEqual(j['stage2_avg_r'], r['configs'][v.MAIN]['pools']['U-D']['avg_r'])
        k = m['stage1_link']
        self.assertTrue(k['same_commit'])
        self.assertEqual((k['eval_files_changed'], k['contact_missing'], k['contact_ud_changes']), ([], [], []))
        self.assertTrue(k['tz']['same'] and k['reference']['same'])
        self.assertNotIn('golden', k)                               # コードを直していなければゴールデンは確かめない
        w = m['clock']['window']
        self.assertTrue(w['same'])
        self.assertEqual(w['weeks_used'], w['weeks_all'])            # 書き出しは使う期間だけ
        self.assertGreater(m['clock']['split_weeks'], 0)
        self.assertEqual(m['clock']['frac_athens_split'], 1.0)
        # 第1段の取引一覧と、第2段で走らせ直した komo135 の取引は同じ
        t1 = pd.read_csv(os.path.join(self.s1, 'stage1_trades.csv.gz'), dtype=str, keep_default_na=False)
        t2 = pd.read_csv(os.path.join(self.s2, 'stage2_trades.csv.gz'), dtype=str, keep_default_na=False)
        self.assertTrue(t1[v.CMP_COLS].equals(t2[t2['src'] == 'komo'][v.CMP_COLS].reset_index(drop=True)))
        with open(os.path.join(self.s2, 'stage2_report.md'), encoding='utf-8') as f:
            rep = f.read()
        self.assertTrue(rep.startswith('# 【ドライラン：数値は無意味】'))
        self.assertIn('**注意：素朴ベースラインの格子・シードが事前登録と違う（テスト用の設定）**', rep)

    def test_stage2_same_with_two_processes(self):
        """子プロセス（spawn）で走らせても同じ結果（初期化で表を足し、仕事ごとの差し替えが残らない）"""
        out = os.path.join(self.tmp, 's2b')
        v.run_stage2(out_dir=out, stage1_dir=self.s1, workers=2, dry_run=True, dev_dir=self.dev, spec=self.spec,
                     naive_p=[0.02, 0.05], naive_seeds=[0, 1], log=lambda s: None)
        self.same_files(self.s2, out, ['stage2_results.json', 'stage2_trades.csv.gz', 'stage2_naive_trades.csv.gz',
                                       'stage2_report.md'])
        self.assertEqual(fs.SYMBOL_ORDER, v.USED)

    def stage1_frames(self):
        tf = os.path.join(self.s1, 'stage1_trades.csv.gz')
        T = OrderedDict()
        tr = pd.read_csv(tf, keep_default_na=False, float_precision='round_trip')
        for c in v.CONFIGS:
            d = tr[tr['config'] == c].copy().reset_index(drop=True)
            d['entry_time'] = pd.to_datetime(d['entry_time'])
            d['exit_time'] = pd.to_datetime(d['exit_time'])
            d['seq'] = np.arange(len(d))
            d['sym_i'] = d['symbol'].map(v.SYMBOLS.index)
            d['src_i'] = 0
            T[c] = d
        return tf, T

    def test_compare_with_stage1_detects_change(self):
        """§7.2: 関門は第1段の U-D の v1.1 の取引一覧と、その判定の印（接触の申告）。それ以外の差は逸脱として記録する（関門は通す）"""
        tf, T = self.stage1_frames()
        c, _ = v.parse_contact(v.dry_manifest(self.spec), required=False)    # 第1段と同じ仮の申告
        r = v.compare_with_stage1(tf, T, self.spec, c)
        self.assertTrue(r['all_match'] and r['gate_ok'] and r['contact_ok'])
        self.assertGreater(r['gate']['stage1'], 0)
        self.assertEqual(r['ud_judged']['stage1'], r['ud_judged']['stage2'])
        self.assertEqual(r['ud_judged']['stage1'], self.r1['stop']['trades'])
        main = T[v.MAIN]
        ud = (main['entry_time'] >= pd.Timestamp(self.spec['ud'][0])).to_numpy()
        self.assertTrue(ud.any() and not ud.all())
        for cfg, row, gate_ok in ((v.REF, 0, True), (v.MAIN, int(np.argmin(ud)), True), (v.MAIN, int(np.argmax(ud)), False)):
            _, T2 = self.stage1_frames()
            T2[cfg].loc[row, 'pnl_r'] += 1e-12
            r = v.compare_with_stage1(tf, T2, self.spec, c)
            self.assertFalse(r['all_match'], (cfg, row))
            self.assertEqual((r['gate_ok'], r['contact_ok']), (gate_ok, gate_ok), (cfg, row))
            self.assertEqual(r['configs'][cfg]['first_difference']['row'], row)
            self.assertTrue(all(x['match'] for c_, x in r['configs'].items() if c_ != cfg))
        _, T2 = self.stage1_frames()
        T2[v.MAIN] = T2[v.MAIN].drop(index=int(np.flatnonzero(ud)[-1]))   # U-D の取引が1件足りない
        r = v.compare_with_stage1(tf, T2, self.spec, c)
        self.assertFalse(r['gate_ok'])
        self.assertEqual(r['gate']['stage1'] - r['gate']['stage2'], 1)
        c2 = json.loads(json.dumps(v.dry_manifest(self.spec)))             # 取引は同じでも、U-D の申告を変えると印が変わる
        c2['contact']['excluded'].append(ent('*', self.spec['ud'][0], self.spec['ud'][1], '仮: U-D に足した'))
        c2, _ = v.parse_contact(c2, required=False)
        r = v.compare_with_stage1(tf, T, self.spec, c2)
        self.assertTrue(r['gate_ok'] and r['all_match'])
        self.assertFalse(r['contact_ok'])
        self.assertEqual(r['ud_judged']['stage2'], 0)
        self.assertIn('contact', r['contact_flags']['first_difference']['stage1'])

    def test_stage2_in_stage1_folder(self):
        """第1段と同じ出力フォルダで第2段を走らせる（--stage1-dir を省く）。結果は第1段を別のフォルダから読んだときと同じ"""
        out = os.path.join(self.tmp, 's12')
        shutil.copytree(self.s1, out)
        r = v.run_stage2(out_dir=out, workers=1, dry_run=True, dev_dir=self.dev, spec=self.spec,
                         naive_p=[0.02, 0.05], naive_seeds=[0, 1], log=lambda s: None)
        self.assertEqual(r['meta']['stage1_dir'], '.')
        self.assertTrue(r['meta']['stage1_consistency']['gate_ok'] and r['meta']['stage1_consistency']['all_match'])
        self.same_files(self.s2, out, ['stage2_trades.csv.gz', 'stage2_naive_trades.csv.gz'])
        self.same_files(self.s1, out, ['stage1_results.json', 'stage1_trades.csv.gz', 'stage1_report.md'])  # 第1段の出力はそのまま
        self.assertEqual(r['verdict']['label'], self.r2['verdict']['label'])
        with open(os.path.join(out, 'stage2_report.md'), encoding='utf-8') as f:
            rep = f.read()
        self.assertIn('U-D の v1.1 の取引', rep)
        self.assertIn('同じコミット', rep)

    def test_stage2_dry_without_stage1(self):
        """ドライランは第1段の出力がなくても通る（照合を省いたと報告する）"""
        out = os.path.join(self.tmp, 's2d')
        r = v.run_stage2(out_dir=out, workers=1, dry_run=True, dev_dir=self.dev, spec=self.spec,
                         naive_p=[0.02], naive_seeds=[0], log=lambda s: None)
        self.assertIsNone(r['meta']['stage1_consistency'])
        self.assertIsNone(r['meta']['stage1_dir'])
        with open(os.path.join(out, 'stage2_report.md'), encoding='utf-8') as f:
            self.assertIn('第1段の出力と照合していない', f.read())

    def test_undecided_when_clock_unknown(self):
        """時刻の判定ができなければ、戦略を走らせずに「未決」と書く"""
        out = os.path.join(self.tmp, 's2c')
        bad = OrderedDict(kind=None, hours=None, label='未決', reason='テスト', weeks_used=0, frac_ny7=float('nan'),
                          frac_athens=float('nan'), const_hours=None, frac_const=float('nan'), o_w_counts=OrderedDict(),
                          per_symbol=OrderedDict())
        with mock.patch.object(v, 'detect_clock', return_value=bad), mock.patch.object(v, 'Runner') as rn:
            r = v.run_stage2(out_dir=out, stage1_dir=self.s1, workers=1, dry_run=True, dev_dir=self.dev, spec=self.spec,
                             naive_p=[0.02], naive_seeds=[0], log=lambda s: None)
            rn.assert_not_called()
        self.assertEqual(r['verdict']['label'], '未決')
        self.assertFalse(os.path.exists(os.path.join(out, 'stage2_trades.csv.gz')))
        with open(os.path.join(out, 'stage2_report.md'), encoding='utf-8') as f:
            self.assertIn('判定：未決', f.read())


class TestProductionPath(unittest.TestCase):
    """本番（ドライランでない）の通り道を、開発データから作った合成の入力で通す（git・凍結の確認だけ省く。数値は無意味）。
    第1段（記録ファイルなし → 事前登録 §2 の記録）→ 第2段（同じ出力フォルダ）、未決、§7.2 の関門で止まる、走らせ直し"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='v11_prod_')
        dev = make_dev_dir(os.path.join(cls.tmp, 'dev'), start='2016-01-01', end='2017-04-01')
        dspec = e2e_spec()
        cls.inp = v.make_dry_inputs(dev, os.path.join(cls.tmp, 'in'), dspec, stage=2, log=lambda s: None)
        cls.spec = dict(dspec, dry_run=False, dry_alias=None, mt5_clock=None, ref_trades=cls.inp['ref_trades'],
                        min_symbols=3, min_symyears=0.5)
        git = mock.patch.object(v, 'git_state', return_value=v.git_state())
        git.start()
        cls.addClassCleanup(git.stop)
        # 第2段の記録: 第1段の記録（除外なし）はそのままで、U-E の期間（U-D の終わりより後）の確認だけを書き足したもの
        cls.man = json.loads(json.dumps(cls.inp['manifest']))
        cls.man['contact'] = {'asked_on': '2026-11-02', 'summary': '仮: 第2段の前の確認（U-E の期間）',
                              'excluded': [ent('XAUUSD', '2017-01-09', '2017-01-31', '仮: fusion 系を見た（U-E）')],
                              'partial': [ent('USDJPY', '2017-02-01', '2017-02-14', '仮: 旧 EA の通知')]}
        cls.out = os.path.join(cls.tmp, 'out')
        real_stop = v.stop_rule
        c = OrderedDict(asked_on='2026-11-01', summary='見ていない', excluded=[], partial=[])
        with mock.patch.object(v, 'prereg_stage1_contact', return_value=(c, [])), \
                mock.patch.object(v, 'stop_rule', side_effect=lambda ud: OrderedDict(real_stop(ud), stop=False)):
            cls.r1 = v.run_stage1(komo_dir=cls.inp['komo_dir'], out_dir=cls.out, workers=1, spec=cls.spec,
                                  log=lambda s: None, require_clean_git=False, today='2026-11-01')
        cls.r2 = cls.stage2(cls.out)

    @classmethod
    def stage2(cls, out, **kw):
        args = dict(komo_dir=cls.inp['komo_dir'], mt5_dir=cls.inp['mt5_dir'], manifest=cls.man, out_dir=out, workers=1,
                    spec=cls.spec, naive_p=[0.02], naive_seeds=[0, 1], log=lambda s: None, require_clean_git=False,
                    today='2026-11-02')
        args.update(kw)
        return v.run_stage2(**args)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy_stage1(self, name):
        out = os.path.join(self.tmp, name)
        os.makedirs(out)
        for f in ('stage1_results.json', 'stage1_trades.csv.gz', 'stage1_report.md', 'stage1_run.log'):
            shutil.copy(os.path.join(self.out, f), out)
        return out

    def test_stage1_production(self):
        m = self.r1['meta']
        self.assertFalse(m['dry_run'])
        self.assertTrue(m['contact']['source'].startswith('事前登録'))
        self.assertEqual((m['contact']['asked_on'], m['run_date']), ('2026-11-01', '2026-11-01'))
        with open(os.path.join(self.out, 'stage1_report.md'), encoding='utf-8') as f:
            rep = f.read()
        self.assertTrue(rep.startswith('# FUSION-CORE v1.1 第1段'))
        self.assertNotIn('ドライラン', rep)
        self.assertIn('**省いた（テスト用の設定）**', rep)
        with open(os.path.join(self.out, 'stage1_run.log'), encoding='utf-8') as f:
            self.assertTrue(f.readline().startswith('=== 実行 第1回 ==='))
        with self.assertRaises(SystemExit) as cm:                  # 各段で1回だけ
            v.run_stage1(komo_dir=self.inp['komo_dir'], out_dir=self.out, workers=1, spec=self.spec, log=lambda s: None,
                         require_clean_git=False)
        self.assertIn('1回だけ', str(cm.exception))

    def test_stage2_production(self):
        r, m = self.r2, self.r2['meta']
        self.assertEqual((m['dry_run'], m['run_date'], m['stage1_dir']), (False, '2026-11-02', '.'))
        self.assertIn(r['verdict']['label'], ('合格', '不合格'))
        self.assertTrue(m['stage1_consistency']['gate_ok'] and m['stage1_consistency']['all_match'])
        self.assertTrue(m['ue_windows']['ok'])
        self.assertEqual(m['contact']['source'], '記録ファイル（--manifest）')
        self.assertTrue(m['stage1_consistency']['contact_ok'] and m['stage1_consistency']['ud_judged']['match'])
        k = m['stage1_link']
        self.assertEqual((k['stage1_run_date'], k['asked_on'], k['run_date'], k['contact_ud_changes']),
                         ('2026-11-01', '2026-11-02', '2026-11-02', []))
        tr = pd.read_csv(os.path.join(self.out, 'stage2_trades.csv.gz'), keep_default_na=False)
        self.assertEqual(set(tr.loc[tr['contact'] != '', 'pool']), {'U-E'})     # 第2段で書き足した申告は U-E にだけ働く
        with open(os.path.join(self.out, 'stage2_report.md'), encoding='utf-8') as f:
            rep = f.read()
        self.assertTrue(rep.startswith('# FUSION-CORE v1.1 第2段'))
        self.assertIn('実行した日：2026-11-02', rep)
        for word in ('第1段の実行日 2026-11-01', '第2段の前の確認 2026-11-02', 'の申告の働きは第1段と同じ',
                     'その判定の印（接触の申告）は全件一致', '独立とみなした値'):
            self.assertIn(word, rep)
        with self.assertRaises(SystemExit) as cm:
            self.stage2(self.out)
        self.assertIn('1回だけ', str(cm.exception))

    def test_stage2_undecided_in_production(self):
        """最低限の量に届かなければ、本番は戦略を走らせずに「未決」と書く（ドライランは続ける）"""
        out = self.copy_stage1('undecided')
        with mock.patch.object(v, 'Runner') as rn:
            r = self.stage2(out, spec=dict(self.spec, min_symbols=8))
            rn.assert_not_called()
        self.assertEqual((r['verdict']['label'], r['verdict']['status']), ('未決', 'undecided'))
        self.assertFalse(os.path.exists(os.path.join(out, 'stage2_trades.csv.gz')))
        with open(os.path.join(out, 'stage2_report.md'), encoding='utf-8') as f:
            self.assertIn('最低限の量', f.read())

    def test_stage2_gate_and_rerun(self):
        """§7.2 の関門（U-D の v1.1 の取引一覧）で止まれば判定しない。結果のファイルができる前の失敗なので、理由を書けば走らせ直せる"""
        out = self.copy_stage1('gate')
        real = v.compare_with_stage1

        def broken(path, T, spec, contact):
            r = real(path, T, spec, contact)
            return OrderedDict(r, gate_ok=False)
        with mock.patch.object(v, 'compare_with_stage1', side_effect=broken):
            with self.assertRaises(SystemExit) as cm:
                self.stage2(out)
        self.assertIn('§7.2', str(cm.exception))
        self.assertTrue(os.path.exists(os.path.join(out, 'stage2_stage1_mismatch.json')))
        self.assertFalse(os.path.exists(os.path.join(out, 'stage2_results.json')))
        with self.assertRaises(SystemExit) as cm:                  # 理由なしには走らせ直さない
            self.stage2(out)
        self.assertIn('--rerun-reason', str(cm.exception))
        r = self.stage2(out, rerun_reason='テスト: 関門の失敗を直した')
        self.assertEqual(r['verdict']['label'], self.r2['verdict']['label'])
        with open(os.path.join(out, 'stage2_run.log'), encoding='utf-8') as f:
            text = f.read()
        self.assertIn('=== 実行 第2回（走らせ直し。理由: テスト: 関門の失敗を直した） ===', text)

    def test_stage2_ud_contact_change_stops(self):
        """第2段の記録で U-D の期間に除外を足すと、本番は何も計算しないうちに止まる（第1段の記録を正とする）。
        実行前の確認をすり抜けても、走らせ直した U-D の v1.1 の取引の判定の印が第1段と違えば、関門と同じく判定しない"""
        out = self.copy_stage1('ud_contact')
        man = json.loads(json.dumps(self.man))
        man['contact']['excluded'].append(ent('*', '2016-07-01', '2016-10-31', '仮: U-D の期間に足した'))
        with mock.patch.object(v, 'Runner') as rn:
            with self.assertRaises(SystemExit) as cm:
                self.stage2(out, manifest=man)
            rn.assert_not_called()
        self.assertIn('U-D の期間', str(cm.exception))
        with mock.patch.object(v, 'contact_ud_changes', return_value=[]):    # 実行前の確認をすり抜けたとき
            with self.assertRaises(SystemExit) as cm:
                self.stage2(out, manifest=man)
        self.assertIn('判定の印（接触の申告）が第1段と違う', str(cm.exception))
        with open(os.path.join(out, 'stage2_stage1_mismatch.json'), encoding='utf-8') as f:
            js = json.load(f)
        self.assertTrue(js['gate_ok'])
        self.assertFalse(js['contact_ok'])
        self.assertLess(js['ud_judged']['stage2'], js['ud_judged']['stage1'])
        self.assertFalse(os.path.exists(os.path.join(out, 'stage2_results.json')))


if __name__ == '__main__':
    unittest.main()
