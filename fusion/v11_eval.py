"""
FUSION-CORE v1.1 の評価（事前登録 fusion/PREREGISTRATION_v1_1.md のとおりに、各段で1回だけ実行する）

  第1段: python -m fusion.v11_eval stage1 --komo-dir DIR --out OUT [--workers 4] [--manifest JSON]
  第2段: python -m fusion.v11_eval stage2 --komo-dir DIR --mt5-dir DIR2 --manifest JSON --out OUT [--workers 4]
  ドライラン（開発データだけを使う。数値は無意味）:
         python -m fusion.v11_eval stage1 --dry-run --dev-dir ISDATA --out OUT
         python -m fusion.v11_eval stage2 --dry-run --dev-dir ISDATA --out OUT

入力
  --komo-dir    komo135/forex-historical-data の1時間足。<銘柄>h1.csv が並んだフォルダか、リポジトリの形（<銘柄>/<銘柄>h1.csv）
  --mt5-dir     利用者の MT5 から書き出した <12銘柄の名前>_H1.csv（§3.2。MT5 の既定のタブ区切り <DATE> <TIME> <OPEN> … でよい）
  --manifest    §2・§3.2 の記録（JSON。下の「記録ファイル」）。第2段は必須。第1段は contact だけを使い、省いたときは
                事前登録 §2 の「第1段の前の確認の結果（日付）」の項目を記録として使う（「除外も「一部汚れ」の記録もなし」と
                書かれているときだけ。除く銘柄×期間があるなら --manifest で渡す。§7.1「§2 の確認を記録してから」）
  --out         出力フォルダ。第1段と第2段で同じフォルダを使う（第2段は、そこにある第1段の出力を読んで確かめる）
  --stage1-dir  第2段だけ。第1段の出力が --out と別のフォルダにあるときに指す（既定は --out）。第2段は、第1段の判定
                （打ち切りなら第2段は行わない）・取引一覧の SHA-256・komo135 のファイルの SHA-256・接触の申告・コードを確かめ、
                走らせ直した komo135 の取引を第1段の取引一覧と比べる
  --dev-dir     ドライランの開発データ（fusion.data.prepare_oanda で作った <銘柄>_H1.csv。2013〜2017 の4銘柄）。
                既定は環境変数 FUSION_DATA_DIR
  --rerun-reason     結果のファイルができる前に失敗した実行を走らせ直す理由（§13。回数と理由をログに残す）
  --code-fix-reason  第2段だけ。第1段の後に評価に使うファイルを直したときの理由（§7.2：結果のファイルができる前の
                     技術的な失敗だけ）。直していなければ要らない。書いた理由は逸脱として結果に残る

出力（--out）
  第1段: stage1_results.json・stage1_report.md（日本語）・stage1_trades.csv.gz（v1.1・fusion・1.5倍の全取引）・stage1_run.log
  第2段: stage2_results.json・stage2_report.md・stage2_trades.csv.gz・stage2_naive_trades.csv.gz（素朴ベースライン）・stage2_run.log
  取引一覧は gzip の時刻を0にして書くので、同じ入力からは同じバイト列になる。SHA-256 を results.json に書く。
  素朴ベースラインは P4 と p の選び方（どちらも判定プールだけ）にしか使わないので、取引一覧には、各系列の判定プールの始まり
  （komo135 は U-D の開始、利用者の系列は U-E の開始）以降にエントリーした取引だけを残す（系列は先頭から走らせる。§6）。

記録ファイル（--manifest。UTF-8 の JSON。第1段と第2段で同じファイルを書き足していけばよい）
  {
    "contact": {                     # §2 の利用者への確認（第1段の前と第2段の前に記録する）
      "asked_on": "2026-11-01",      # 確かめた日（本番では必須。第2段の前に確かめ直したら、その日に書き換える）
      "summary": "利用者の答えの要約",
      "excluded": [                  # fusion 系（EA のテスター・パネル、ダッシュボード、Python）で成績を見た銘柄×期間 → 判定から除き、別に報告
        {"symbol": "EURUSD", "from": "2023-01-01", "to": "2023-06-30", "reason": "EA のパネル"}],
      "partial": [                   # 旧 EA（MA スロープ・4P-Score）のテスター・通知、覚えていない・分からない → 「一部汚れ」。判定に使い、除いた値も併記
        {"symbol": "*", "from": "2022-03-05", "to": "2026-10-31", "reason": "旧 EA の通知を受けていた"}]
    },
    "broker": {"name": "ブローカー名", "server": "サーバー名", "account_type": "demo か real", "exported_on": "2026-11-02"},  # 第2段
    "symbol_map": {                  # 第2段。12銘柄すべてを書く
      "EURUSD": "EURUSD.a",          # ブローカーの銘柄名（ファイルは --mt5-dir/EURUSD_H1.csv）
      "EURCHF": {"broker_symbol": null, "reason": "ブローカーに銘柄がない"}
    }
  }
  - symbol は12銘柄の名前か "*"（全銘柄）。from・to は換算後（NY+7）の日付で、両端の日を含む。取引はエントリー時刻で当てはめる。
    当てはめるのは判定プール（U-D・U-E）の取引だけ（§2 の確認は 2020-05-15 以降のデータについてのもの）。
  - 第2段の contact には、第1段の記録（excluded・partial）をそのまま残し、2022-03-05〜2026-10-31 の確認を書き足す
    （本番の第2段は、第1段の記録が消えていると止まる。U-D の判定に使う取引が第1段と変わらないように）。
  - EA のパネルを見た場合の from は「EA を付けた日から InpHistoryBars 本（既定10,000本。H1 は1週およそ120本）さかのぼった日」（§2）。

守ること（§12・§13）
  - fusion/strategy.py・broker.py・final_eval.py・data.py は変えない。12銘柄の一覧・FX の一覧（11銘柄）・プールの期間・価格の桁・
    3銘柄の s_nom・乱数の番号は、このファイルが持つ。
  - 仕事を走らせるプロセスの初期化で、strategy.S_NOM（＝broker.NOMINAL_SPREAD）に3銘柄を、strategy.SYMBOL_ORDER に5銘柄（番号7〜11）を
    一時的に足す（1プロセスで走らせるときは終わったら戻す。子プロセスでは終わるときに戻す）。v1.0 の7銘柄の番号は変えない。
  - スプレッド前提1.5倍の構成と、利用者の系列の素朴ベースライン（SYMBOL_ORDER を「100個の空き＋12銘柄」にして番号を＋100）は、
    仕事ごとに表を差し替えて走らせ、必ず戻す。Bid を仲値にそろえる s_nom/2 は、このファイルの表の値を使う（1.5倍にしない）。
  - final_eval から使うのは、定数に頼らない関数（summary・month_block_ci・monthly_r・sharpe・moments・deflated_sharpe・drop_top・
    judge_p1・judge_p3・judge_p5）だけ。
  - 第1段は §7 の「第1段で出すもの」（構成ごとの U-D・U-X の取引数・平均R・標準誤差、打ち切りの判定、データ源の照合、切断テスト）
    だけを出す。P1〜P6・素朴ベースライン・PSR は計算もしない。
  - 本番は、次のどれかに当たれば何も計算しないうちに止まる：評価に使うファイル（EVAL_FILES）に未コミットの変更がある、
    事前登録に「まだ凍結していない」の注記が残っている、データ・記録ファイルがそろっていない、利用者のファイルが H1 でない・
    換算できない、第2段の期限（2027-02-01）を過ぎた、第1段の後に評価に使うファイルが変わったのに --code-fix-reason がない。
    結果のファイルがすでにある出力フォルダでは走らない（各段で1回だけ）。結果のファイルができる前に失敗したときだけ、
    --rerun-reason に理由を書いて走らせ直せる（回数と理由をログに残す）。
  - 第2段は komo135 の3構成を走らせ直し、第1段の取引一覧と比べる。U-D の v1.1 の取引が1件でも違えば判定しない（§7.2）。
    それ以外の差は逸脱として記録する。
  - 時刻の判定ができない・最低限の量に届かないときは、戦略を走らせずに「未決」と書く（§3.2。これも結果なので走らせ直さない）。
  - ドライランは開発データだけを使う（komo135 のデータ・利用者のデータは読まない）。--komo-dir・--mt5-dir・--manifest は渡さない。
"""
import argparse
import contextlib
import gzip
import hashlib
import io
import json
import math
import multiprocessing as mp
import multiprocessing.util as mp_util
import os
import platform
import re
import resource
import subprocess
import time
from collections import Counter, OrderedDict

import numpy as np
import pandas as pd

from fusion import data as fd
from fusion import final_eval as fe
from fusion import strategy as fs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAN = float('nan')
HOUR = pd.Timedelta(hours=1)
DAY = pd.Timedelta(days=1)
YEAR = pd.Timedelta(days=365.25)

# ---------------------------------------------------------------- 銘柄（§3.1・§6・§12）
SYMBOLS = ['EURUSD', 'GBPUSD', 'EURJPY', 'AUDUSD', 'USDCAD', 'AUDJPY', 'XAUUSD',     # 番号 0〜6（v1.0 と同じ）
           'USDJPY', 'GBPJPY', 'EURGBP', 'EURCHF', 'USDCHF']                         # 番号 7〜11
USED = SYMBOLS[:7]                                   # このリポジトリで使った7銘柄（v1.0 の SYMBOL_ORDER）
NEW = SYMBOLS[7:]                                    # 使ったことのない5銘柄（U-X）
FX = [s for s in SYMBOLS if s != 'XAUUSD']           # FX の11銘柄（警告の GAP_FALLBACK・時刻の判定）
CHF = ['USDCHF', 'EURCHF']
DIGITS = OrderedDict((s, 2 if s == 'XAUUSD' else (3 if s.endswith('JPY') else 5)) for s in SYMBOLS)
EXTRA_S_NOM = OrderedDict([('EURGBP', 0.00015), ('USDCHF', 0.00015), ('EURCHF', 0.00020)])    # SPEC §10.3 の表にない3銘柄
S_NOM = OrderedDict((s, EXTRA_S_NOM[s] if s in EXTRA_S_NOM else float(fs.S_NOM[s])) for s in SYMBOLS)
USER_OFFSET = 100                                    # 利用者の系列の素朴ベースラインの番号（100〜111）

# ---------------------------------------------------------------- 構成（§5・§6）
MAIN, REF, WIDE = 'v1.1', 'fusion', 'v1.1_s1.5'
CONFIGS = [MAIN, REF, WIDE]
CONFIG_LABEL = {MAIN: 'v1.1（F+h1trans）', REF: 'fusion（v1.0。参考）', WIDE: 'v1.1 スプレッド前提1.5倍（参考）'}
SPREAD_MULT = {WIDE: 1.5}
NAIVE_P = [0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02, 0.03, 0.05, 0.08]
NAIVE_SEEDS = list(range(20))

# ---------------------------------------------------------------- 統計・判定の定数（§3.2・§8・§9）
P2_MIN_N, P2_FRAC = 30, 0.60
P4_MARGIN = 0.10
P6_MIN = 0.95
NAIVE_TOL = 0.20
TEN_MONTH_MIN = 15
GAP_PER_YEAR_MAX = 1.0
CLOCK_NEED = 0.95                  # 時刻の判定：週の95%以上で一致
CLOCK_MIN_BARS = 100               # 足が100本未満の週は判定に使わない
INT_TOL = 1e-6                     # 価格の整数倍の確認
JUDGE_POOLS = ['U-D', 'U-E']
HALVES = ['前半', '後半']
CHF_ENTRY_BEFORE = pd.Timestamp('2015-01-16')        # §4: entry_time < 2015-01-16 00:00
CHF_EXIT_FROM = pd.Timestamp('2015-01-15')           #     かつ 決済の足 ≥ 2015-01-15 00:00

# 評価の結果を決めるファイル（§13）。本番はこれらがコミット済みであること
PREREG = 'fusion/PREREGISTRATION_v1_1.md'
EVAL_FILES = list(fe.EVAL_FILES) + [PREREG, 'fusion/v11_eval.py']
REF_TRADES = os.path.join(ROOT, 'fusion', 'results', 'final_eval_trades_main.csv.gz')
FROZEN_MARK = 'まだ凍結していない'                     # 事前登録の冒頭の注記。凍結するときに消す（残っていれば本番は走らない）
STAGE2_DEADLINE = pd.Timestamp('2027-02-01')         # §7.2: この日までに第2段を行えなければ「未決」のまま閉じる
STAGE1_CONTACT_RE = re.compile(r'第1段の前の確認の結果（(\d{4}-\d{2}-\d{2})）')   # 事前登録 §2 に書いた第1段の前の確認
NO_CONTACT_MARK = '除外も「一部汚れ」の記録もなし'      # その記録が「除く銘柄×期間がない」と言っていること

PRICE = ['Open', 'High', 'Low', 'Close']
BASE_COLS = ['symbol', 'entry_time', 'exit_time', 'direction', 'entry', 'initial_sl', 'risk', 'pnl_r', 'exit_reason',
             'bars_held', 'mfe_r', 'mae_r']
FLAG_COLS = ['config', 'src', 'pool', 'half', 'contact', 'ue_after', 'chf_excl', 'src_check']
CMP_COLS = ['config', 'src'] + BASE_COLS              # 第1段と第2段で一致を確かめる列
SRC_ORDER = {'komo': 0, 'mt5': 1}


def naive_name(p, seed):
    return f'naive:p={p}:seed={seed}'


def is_naive(cfg):
    return str(cfg).startswith('naive')


def switches(cfg):
    """構成名 → strategy.run_h1 のスイッチ（v1.1 と1.5倍は VARIANTS['F+h1trans']、fusion は既定）"""
    if cfg in (MAIN, WIDE):
        return dict(fs.VARIANTS['F+h1trans'])
    if cfg == REF:
        return dict(fs.VARIANTS['fusion'])
    if is_naive(cfg):
        return fs.config(cfg)
    raise KeyError(cfg)


# ---------------------------------------------------------------- 評価プール（§3.2・§4）
DRY_ALIAS = OrderedDict([('EURUSD', 'EURUSD'), ('GBPUSD', 'GBPUSD'), ('EURJPY', 'EURJPY'), ('XAUUSD', 'XAUUSD'),
                         ('USDJPY', 'EURJPY'), ('GBPJPY', 'EURJPY'), ('EURGBP', 'EURUSD'), ('EURCHF', 'EURUSD'),
                         ('USDCHF', 'GBPUSD')])


def make_spec(dry_run=False):
    """本番は事前登録のプール。ドライランは開発データ（2013〜2017）の中に作った仮のプール（数値は無意味）"""
    spec = dict(
        dry_run=False,
        symbols=list(SYMBOLS),
        komo_clip=None,                                    # 換算後の足を切る範囲（両端の日を含む）。本番は切らない
        ud=('2020-05-15', '2022-03-04'),                   # U-D（判定）: 12銘柄、komo135
        ux=('2013-03-01', '2020-05-14'),                   # U-X（参考）: 新しい5銘柄、komo135
        ux_from=OrderedDict(EURCHF='2015-03-01'),
        ue=('2022-03-05', '2026-10-31'),                   # U-E（判定）: 利用者の MT5
        ue_after=('2024-09-01', '2026-10-31'),             # U-E後（参考）
        src_check=('2018-01-01', '2020-05-14'),            # データ源の照合（使用済み7銘柄の fusion）
        midpoints=OrderedDict([('U-D', '2021-04-09 12:00'), ('U-E', '2024-07-03 00:00')]),   # P3（事前登録の値と照合する）
        mt5_clip=('2021-12-01', '2026-10-31'),             # 利用者の系列で使う足（換算後。両端の日を含む）
        ue_late='2021-12-01',                              # 最初の足がこれ（0時）より後 → 「最初の足＋3か月」から数える
        ue_drop='2023-01-01',                              # 最初の足がこれ（0時）より後 → 除く
        cut=('EURUSD', '2021-06-01'),                      # 切断テスト（v1.1）
        psr_months=('2020-05', '2026-10'),
        min_symbols=8, min_symyears=30.0,                  # §3.2 の最低限の量
        komo_rows=57600, komo_last='2022-03-04 23:00',     # §3.1 のファイル（違えば止める）
        ux_first_by='2012-12-01',                          # U-X の銘柄は3か月のウォームアップがあること
        ref_trades=REF_TRADES, ref_config='fusion', ref_pool='U-B',
        dry_alias=None, mt5_clock=None,
    )
    if not dry_run:
        return spec
    return dict(
        spec,
        dry_run=True,
        symbols=[s for s in SYMBOLS if s in DRY_ALIAS],
        komo_clip=('2013-01-01', '2017-12-31'),
        ud=('2016-01-01', '2016-12-31'),
        ux=('2014-03-01', '2015-06-30'),
        ue=('2017-01-01', '2017-12-29'),
        ue_after=('2017-07-01', '2017-12-29'),
        src_check=('2015-01-01', '2015-12-31'),
        midpoints=None,
        mt5_clip=('2016-10-03', '2017-12-31'),             # 2016-10-03 は月曜（本番の 2021-12-01 と同じく、最初の足が区間の始まり）
        ue_late='2016-10-03', ue_drop='2017-04-01',
        cut=('EURUSD', '2016-06-01'),
        psr_months=('2016-01', '2017-12'),
        komo_rows=None, komo_last=None, ux_first_by=None,
        ref_trades=None,
        dry_alias=OrderedDict(DRY_ALIAS), mt5_clock='athens',
    )


def day_range(a, b):
    """表の期間 a〜b（両端の日を含む）→ [a の0時, b の翌日0時)"""
    return pd.Timestamp(a), pd.Timestamp(b) + DAY


def midpoint(a, b):
    lo, hi = day_range(a, b)
    return lo + (hi - lo) / 2


def pool_midpoints(spec):
    mids = OrderedDict([('U-D', midpoint(*spec['ud'])), ('U-E', midpoint(*spec['ue']))])
    for p, txt in (spec.get('midpoints') or {}).items():
        if mids[p] != pd.Timestamp(txt):
            raise ValueError(f'{p} の中点 {mids[p]} が事前登録の値 {txt} と一致しない')
    return mids


# ---------------------------------------------------------------- strategy の表の一時的な追加と、仕事ごとの差し替え（§12）
def install_tables():
    """strategy.S_NOM（＝broker.NOMINAL_SPREAD）に3銘柄を、strategy.SYMBOL_ORDER に5銘柄（番号7〜11）を足す。戻り値は元に戻す関数"""
    old_order = fs.SYMBOL_ORDER
    if list(old_order) != USED:
        raise RuntimeError(f'strategy.SYMBOL_ORDER が v1.0 の7銘柄でない（前の差し替えが残っている）: {old_order}')
    clash = [s for s in EXTRA_S_NOM if s in fs.S_NOM]
    if clash:
        raise RuntimeError(f'strategy.S_NOM にすでに {clash} がある（ほかの処理が足したまま）')
    for s, v in EXTRA_S_NOM.items():
        fs.S_NOM[s] = v
    fs.SYMBOL_ORDER = list(old_order) + list(NEW)

    def restore():
        fs.SYMBOL_ORDER = old_order
        for s in EXTRA_S_NOM:
            fs.S_NOM.pop(s, None)
    return restore


@contextlib.contextmanager
def tables_installed():
    restore = install_tables()
    try:
        yield
    finally:
        restore()


@contextlib.contextmanager
def job_tables(src, sym, cfg):
    """仕事ごとの差し替え。スプレッド前提1.5倍の構成は s_nom を1.5倍に、利用者の系列の素朴ベースラインは SYMBOL_ORDER を
    「100個の空き＋12銘柄」にする（番号＋100）。前の仕事の差し替えが残っていないことを先に確かめ、終わったら必ず戻す"""
    order = fs.SYMBOL_ORDER
    if list(order) != USED + NEW:
        raise RuntimeError('strategy.SYMBOL_ORDER が12銘柄の表でない（表を足していないか、前の仕事の差し替えが残っている）')
    if fs.S_NOM.get(sym) != S_NOM[sym]:
        raise RuntimeError(f'strategy.S_NOM[{sym}]={fs.S_NOM.get(sym)} が表の {S_NOM[sym]} でない')
    try:
        if cfg in SPREAD_MULT:
            fs.S_NOM[sym] = S_NOM[sym] * SPREAD_MULT[cfg]
        if src == 'mt5' and is_naive(cfg):
            fs.SYMBOL_ORDER = [None] * USER_OFFSET + list(SYMBOLS)
        yield
    finally:
        fs.S_NOM[sym] = S_NOM[sym]
        fs.SYMBOL_ORDER = order


# ---------------------------------------------------------------- データ（§3）
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def athens_to_server(times):
    """欧州の夏時間に連動する GMT+2/+3 の壁時計（tz 名 Europe/Athens）→ UTC → NY+7（fusion.data.utc_to_server）。
    夏時間の切り替えの重なり・抜けに当たる時刻は例外にする（市場が閉まっている日曜なので起きないはず）"""
    loc = pd.DatetimeIndex(times).tz_localize('Europe/Athens', ambiguous='raise', nonexistent='raise')
    return pd.DatetimeIndex(fd.utc_to_server(loc.tz_convert('UTC').tz_localize(None)))


def server_to_utc(times):
    """NY+7 → UTC（テスト・ドライランの入力を作るための逆変換）"""
    ny = (pd.DatetimeIndex(times) - pd.Timedelta(hours=7)).tz_localize('America/New_York', ambiguous='raise',
                                                                        nonexistent='raise')
    return ny.tz_convert('UTC').tz_localize(None)


def to_server(raw_times, clock):
    """生の時刻 → NY+7（§3.2 の換算）。clock: {'kind': 'ny7' | 'athens' | 'fixed', 'hours': h}"""
    t = pd.DatetimeIndex(raw_times)
    kind = clock['kind']
    if kind == 'ny7':
        return t
    if kind == 'athens':
        return athens_to_server(t)
    if kind == 'fixed':
        return pd.DatetimeIndex(fd.utc_to_server(t - pd.Timedelta(hours=clock['hours'])))
    raise ValueError(f'換算の種類が分からない: {clock}')


def from_server(times, clock):
    """NY+7 → その時計の生の時刻（to_server の逆。テスト・ドライラン用）"""
    t = pd.DatetimeIndex(times)
    kind = clock['kind']
    if kind == 'ny7':
        return t
    utc = server_to_utc(t)
    if kind == 'athens':
        return utc.tz_localize('UTC').tz_convert('Europe/Athens').tz_localize(None)
    if kind == 'fixed':
        return utc + pd.Timedelta(hours=clock['hours'])
    raise ValueError(f'換算の種類が分からない: {clock}')


def ohlc_bad(df):
    """四本値の矛盾（高値＜始値・終値の大きい方、安値＞小さい方、高値＜安値）の件数。直さない"""
    o, h, l, c = (df[k].to_numpy(float) for k in PRICE)
    return int(((h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (h < l)).sum())


def _finish_series(df, sym, clip):
    """換算後の時刻で土日の足を除き、同じ時刻の足は最初のものを使い、時刻順にして、四本値に s_nom/2（表の値）を足す"""
    weekend = df.index.dayofweek >= 5
    df = df[~weekend]
    dup = df.index.duplicated(keep='first')
    df = df[~dup]
    was_sorted = bool(df.index.is_monotonic_increasing)
    if not was_sorted:
        df = df.sort_index(kind='mergesort')
    df = df.copy()
    df[PRICE] = df[PRICE] + S_NOM[sym] / 2                # Bid → 仲値（水準をそろえるだけ。1.5倍の構成でもこの値）
    full_first = df.index[0] if len(df) else None
    full_last = df.index[-1] if len(df) else None
    if clip is not None:
        lo, hi = day_range(*clip)
        df = df[(df.index >= lo) & (df.index < hi)]
    df.index.name = 'Time'
    rec = OrderedDict(weekend_dropped=int(weekend.sum()), duplicates=int(dup.sum()), sorted=was_sorted,
                      server_first=full_first, server_last=full_last,
                      first=df.index[0] if len(df) else None, last=df.index[-1] if len(df) else None, bars=int(len(df)),
                      ohlc_inconsistent=ohlc_bad(df), s_nom=S_NOM[sym], shift=S_NOM[sym] / 2)
    return df, rec


def find_komo_files(komo_dir, symbols):
    """<DIR>/<銘柄>h1.csv か <DIR>/<銘柄>/<銘柄>h1.csv"""
    out = OrderedDict()
    if not komo_dir:
        return out
    for s in symbols:
        for p in (os.path.join(komo_dir, f'{s}h1.csv'), os.path.join(komo_dir, s, f'{s}h1.csv')):
            if os.path.isfile(p):
                out[s] = p
                break
    return out


def load_komo(path, sym, clip=None):
    """komo135 の1時間足 → NY+7 の仲値の OHLC（§3.1 の変換をこの順で行う）
      1) 価格＝round(生の値)÷10^桁（円のペア3、XAUUSD 2、ほか5）。すべての価格 x が |x·10^桁 − round(x·10^桁)| < 1e−6 か確かめる
      2) 時刻を Europe/Athens の壁時計として UTC に戻し、fusion.data.utc_to_server で NY+7 に換算する
      3) 換算後の時刻で土日の足を除き、同じ時刻の足は最初のものを使う
      4) 四本値に s_nom/2 を足す（Bid → 仲値）
    戻り値 (足, 記録)。記録に SHA-256・行数・期間・確認の結果を入れる"""
    raw = pd.read_csv(path)
    names = {str(c).strip().lower(): c for c in raw.columns}
    miss = [c for c in ('date', 'open', 'high', 'low', 'close') if c not in names]
    if miss:
        raise ValueError(f'{path}: komo135 の列（Date,open,high,low,close,tick_volume）がない: {miss}')
    scale = 10.0 ** DIGITS[sym]
    rawp = np.column_stack([pd.to_numeric(raw[names[c]], errors='coerce').to_numpy(dtype=float)
                            for c in ('open', 'high', 'low', 'close')])
    ints = np.round(rawp)
    x = ints / scale
    xs = x * scale
    with np.errstate(invalid='ignore'):
        dev = np.abs(xs - np.round(xs))
        frac = ~(np.abs(rawp - ints) < INT_TOL)             # 浮動小数の誤差を超える端数（NaN を含む）
    int_ok = bool(np.isfinite(dev).all() and (dev < INT_TOL).all())
    t_raw = pd.DatetimeIndex(pd.to_datetime(raw[names['date']].astype(str).str.strip(), format='ISO8601'))
    srv = athens_to_server(t_raw)
    vol = (pd.to_numeric(raw[names['tick_volume']], errors='coerce').to_numpy(dtype=float)
           if 'tick_volume' in names else np.zeros(len(raw)))
    df = pd.DataFrame(x, index=srv, columns=PRICE)
    df['Volume'] = vol
    df, rec = _finish_series(df, sym, clip)
    info = OrderedDict(symbol=sym, file=os.path.basename(path), sha256=sha256_of(path), rows=int(len(raw)),
                       raw_first=t_raw.min() if len(t_raw) else None, raw_last=t_raw.max() if len(t_raw) else None,
                       digits=DIGITS[sym], int_check=int_ok,
                       int_check_max_dev=float(np.nanmax(dev)) if np.isfinite(dev).any() else NAN,
                       raw_fraction_values=int(frac.sum()), raw_fraction_rows=int(frac.any(axis=1).sum()),
                       clock='Europe/Athens → UTC → NY+7')
    info.update(rec)
    return df, info


def _decode(path):
    with open(path, 'rb') as f:
        b = f.read()
    if b.startswith(b'\xff\xfe') or b.startswith(b'\xfe\xff'):
        return b.decode('utf-16')                           # MT5 が UTF-16 で書いた場合
    if b.startswith(b'\xef\xbb\xbf'):
        return b[3:].decode('utf-8')
    for enc in ('utf-8', 'cp932'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('latin-1')


def read_mt5_raw(path):
    """MT5 の書き出し（タブ区切り <DATE> <TIME> <OPEN> … と、カンマ区切りの Date,Time,… / Time,…）を、生の時刻のまま読む。
    列の読み方は fusion.data.load_mt5_csv と同じ。土日の足・重複・並び順はそのまま（§3.2 の読み込みの順序。換算の後で処理する）"""
    text = _decode(path)
    head = text.split('\n', 1)[0]
    sep = '\t' if '\t' in head else (';' if ';' in head and ',' not in head else ',')
    raw = pd.read_csv(io.StringIO(text), sep=sep)
    raw.columns = [str(c).strip().strip('<>').strip().upper() for c in raw.columns]
    if 'DATE' in raw.columns and 'TIME' in raw.columns:
        s = (raw['DATE'].astype(str).str.strip().str.replace('.', '-', regex=False) + ' '
             + raw['TIME'].astype(str).str.strip())
    else:
        key = next((c for c in raw.columns if c in ('DATE', 'TIME', 'DATETIME', 'GMT TIME', 'TIMESTAMP')), None)
        if key is None:
            raise ValueError(f'{path}: 時刻の列がない（{list(raw.columns)}）')
        s = raw[key].astype(str).str.strip().str.replace('.', '-', regex=False)
    miss = [c for c in ('OPEN', 'HIGH', 'LOW', 'CLOSE') if c not in raw.columns]
    if miss:
        raise ValueError(f'{path}: 価格の列がない: {miss}')
    ts = pd.DatetimeIndex(pd.to_datetime(s, format='ISO8601'))
    vol = next((c for c in ('TICKVOL', 'VOLUME', 'VOL') if c in raw.columns), None)
    df = pd.DataFrame({'Open': pd.to_numeric(raw['OPEN'], errors='coerce').to_numpy(float),
                       'High': pd.to_numeric(raw['HIGH'], errors='coerce').to_numpy(float),
                       'Low': pd.to_numeric(raw['LOW'], errors='coerce').to_numpy(float),
                       'Close': pd.to_numeric(raw['CLOSE'], errors='coerce').to_numpy(float),
                       'Volume': pd.to_numeric(raw[vol], errors='coerce').to_numpy(float) if vol else 0.0}, index=ts)
    return df


def bar_step(times):
    """足の間隔の最頻値（H1 でない書き出しを、何も計算しないうちに見つけるため。fusion.data.infer_tf と同じ考え方）"""
    t = pd.DatetimeIndex(times).unique().sort_values()
    if len(t) < 2:
        return None
    return pd.Series(t[1:] - t[:-1]).mode().iloc[0]


def load_mt5(path, sym, clock, clip, raw=None):
    """利用者の MT5 の足 → NY+7 の仲値（§3.2）: 生の時刻のまま読み、判定した時計で換算してから、換算後の時刻で土日の足を除き、
    同じ時刻の足は最初のものを使う。s_nom/2 を足し、換算後の clip の範囲（両端の日を含む）だけを使う。
    raw: read_mt5_raw で読み込み済みのもの（同じファイルを2回読まないため）"""
    raw = read_mt5_raw(path) if raw is None else raw
    df = raw.copy()
    df.index = to_server(raw.index, clock)
    df, rec = _finish_series(df, sym, clip)
    info = OrderedDict(symbol=sym, file=os.path.basename(path), sha256=sha256_of(path), rows=int(len(raw)),
                       raw_first=raw.index.min() if len(raw) else None, raw_last=raw.index.max() if len(raw) else None,
                       clock=clock_label(clock))
    info.update(rec)
    return df, info


# ---------------------------------------------------------------- 時刻の判定（§3.2）
WEEK_ANCHOR = pd.Timestamp('2000-01-01 12:00')      # 土曜 12:00。生の時刻の「土曜12:00〜次の土曜12:00」を1週とする


def _holiday_week(start):
    """週（start から7日）が 12/24〜1/3 のどれかの日を含むか"""
    for k in range(8):                                     # 土曜12:00〜次の土曜12:00 は8つの暦日にかかる
        d = (start + pd.Timedelta(days=k)).date()
        if (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day <= 3):
            return True
    return False


def week_rows(raw_times):
    """生の時刻 → 週ごとの記録。o_w＝（週の最後の足の開始時刻＋1時間）−（その週の金曜 17:00 NY を UTC にしたもの）。
    ①の予想＝その金曜 17:00 の NY の UTC 時差＋7時間、②の予想＝同じ時点の Europe/Athens の UTC 時差"""
    t = pd.DatetimeIndex(raw_times).unique().sort_values()
    if len(t) == 0:
        return []
    k = np.asarray((t - WEEK_ANCHOR) // pd.Timedelta(days=7), dtype=np.int64)
    out = []
    for wk in np.unique(k):
        sel = t[k == wk]
        start = WEEK_ANCHOR + pd.Timedelta(days=7) * int(wk)
        friday = (start + pd.Timedelta(days=6)).normalize()                  # start は土曜 → 6日後が金曜
        f_ny = (friday + pd.Timedelta(hours=17)).tz_localize('America/New_York')
        f_utc = f_ny.tz_convert('UTC').tz_localize(None)
        out.append(OrderedDict(week_start=start, bars=int(len(sel)), last=sel[-1], holiday=_holiday_week(start),
                               o_w=(sel[-1] + HOUR) - f_utc, ny7=pd.Timedelta(f_ny.utcoffset()) + pd.Timedelta(hours=7),
                               athens=pd.Timedelta(f_ny.tz_convert('Europe/Athens').utcoffset())))
    return out


def _hours(td):
    return float(td / HOUR)


def detect_clock(raw_by_symbol, need=CLOCK_NEED, min_bars=CLOCK_MIN_BARS):
    """§3.2 の時刻の判定。raw_by_symbol: {FX の銘柄: 生の時刻}。12/24〜1/3 を含む週と足が100本未満の週を除き、
    残りの銘柄×週の o_w で、①NY+7（米国の夏時間に連動）②Europe/Athens（欧州の夏時間に連動）③一定の時差 h のうち、
    95%以上で一致するものを採る。①と②の両方なら①。どれにも当たらなければ未決（kind=None）"""
    rows, per_symbol = [], OrderedDict()
    for sym, t in raw_by_symbol.items():
        w = week_rows(t)
        used = [r for r in w if not r['holiday'] and r['bars'] >= min_bars]
        per_symbol[sym] = OrderedDict(
            weeks=len(w), used=len(used), holiday=sum(1 for r in w if r['holiday']),
            short=sum(1 for r in w if not r['holiday'] and r['bars'] < min_bars),
            frac_ny7=float(np.mean([r['o_w'] == r['ny7'] for r in used])) if used else NAN,
            frac_athens=float(np.mean([r['o_w'] == r['athens'] for r in used])) if used else NAN)
        rows += used
    n = len(rows)
    res = OrderedDict(kind=None, hours=None, label='未決', need=need, min_bars=min_bars, weeks_used=n,
                      frac_ny7=NAN, frac_athens=NAN, const_hours=None, frac_const=NAN, o_w_counts=OrderedDict(),
                      per_symbol=per_symbol)
    if n == 0:
        res['reason'] = '判定に使える週がない'
        return res
    f1 = float(np.mean([r['o_w'] == r['ny7'] for r in rows]))
    f2 = float(np.mean([r['o_w'] == r['athens'] for r in rows]))
    cnt = Counter(r['o_w'] for r in rows)
    h, c = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    whole = (h % HOUR) == pd.Timedelta(0)
    res.update(frac_ny7=f1, frac_athens=f2, const_hours=_hours(h), frac_const=c / n,
               o_w_counts=OrderedDict((f'{_hours(k):+g}', v) for k, v in sorted(cnt.items())))
    if f1 >= need:
        res.update(kind='ny7', label='① NY+7（米国の夏時間に連動）。そのまま使う')
    elif f2 >= need:
        res.update(kind='athens', label='② GMT+2/+3（欧州の夏時間に連動）。Europe/Athens で UTC に戻して NY+7 に換算')
    elif c / n >= need and whole:
        res.update(kind='fixed', hours=int(round(_hours(h))),
                   label=f'③ 一定の時差 {_hours(h):+g} 時間。その時差で UTC に戻して NY+7 に換算')
    else:
        res['reason'] = '①②③のどれも週の95%に届かない'
    return res


def clock_label(clock):
    if clock is None:
        return '—'
    return {'ny7': 'NY+7（そのまま）', 'athens': 'Europe/Athens → UTC → NY+7'}.get(
        clock['kind'], f"UTC{clock.get('hours', 0):+d} → UTC → NY+7")


# ---------------------------------------------------------------- 記録ファイル（§2・§3.2）
def _date(x):
    s = str(x).strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        raise ValueError(f'日付は YYYY-MM-DD で書く: {x!r}')
    return pd.Timestamp(s)


def parse_period(e):
    sym = str(e['symbol']).strip().upper()
    if sym != '*' and sym not in SYMBOLS:
        raise ValueError(f'銘柄 {sym} は12銘柄にない（全銘柄は "*"）')
    a, b = _date(e['from']), _date(e['to'])
    if b < a:
        raise ValueError(f'to（{b.date()}）が from（{a.date()}）より前')
    return OrderedDict([('symbol', sym), ('from', str(a.date())), ('to', str(b.date())),
                        ('reason', str(e.get('reason') or '')), ('lo', a), ('hi', b + DAY)])


def load_manifest(manifest):
    """記録ファイル（パスか dict）→ dict"""
    if manifest is None:
        return None
    if isinstance(manifest, dict):
        return manifest
    with open(manifest, encoding='utf-8-sig') as f:
        return json.load(f)


def parse_contact(man, required):
    """§2 の利用者への確認の記録 → (contact, 問題)。excluded は判定から除き、partial は「一部汚れ」として印を付ける"""
    problems = []
    c = (man or {}).get('contact')
    if not isinstance(c, dict):
        if required:
            problems.append('記録ファイル（--manifest）に contact（§2 の利用者への確認）がない')
        c = {}
    asked = str(c.get('asked_on') or '').strip()
    if required and not asked:
        problems.append('contact.asked_on（利用者に確かめた日）がない')
    out = OrderedDict(asked_on=asked, summary=str(c.get('summary') or ''), excluded=[], partial=[])
    for key in ('excluded', 'partial'):
        items = c.get(key) or []
        if not isinstance(items, list):
            problems.append(f'contact.{key} はリストで書く')
            continue
        for i, e in enumerate(items):
            try:
                out[key].append(parse_period(e))
            except (KeyError, ValueError, TypeError) as ex:
                problems.append(f'contact.{key}[{i}]: {ex}')
    return out, problems


def parse_stage2_manifest(man, required):
    """§3.2 の記録（ブローカー・銘柄の対応表）→ (broker, symbol_map, 問題)。symbol_map: {銘柄: {broker_symbol, reason}}"""
    problems = []
    man = man or {}
    b = man.get('broker') if isinstance(man.get('broker'), dict) else {}
    broker = OrderedDict((k, str(b.get(k) or '').strip()) for k in ('name', 'server', 'account_type', 'exported_on'))
    if required:
        miss = [k for k, v in broker.items() if not v]
        if miss:
            problems.append('broker の ' + '・'.join(miss) + ' がない（§3.2 の記録）')
    raw = man.get('symbol_map') if isinstance(man.get('symbol_map'), dict) else {}
    smap = OrderedDict()
    for s in SYMBOLS:
        if s not in raw:
            if required:
                problems.append(f'symbol_map に {s} がない（12銘柄すべてを書く。対応がなければ broker_symbol を null にして理由を書く）')
            smap[s] = OrderedDict(broker_symbol=None, reason='記録にない')
            continue
        v = raw[s]
        if isinstance(v, str) or v is None:
            v = {'broker_symbol': v}
        bs = v.get('broker_symbol')
        bs = str(bs).strip() if bs is not None and str(bs).strip() else None
        reason = str(v.get('reason') or '')
        if bs is None and required and not reason:
            problems.append(f'symbol_map の {s}: 対応がない理由（reason）を書く')
        smap[s] = OrderedDict(broker_symbol=bs, reason=reason)
    extra = [k for k in raw if k not in SYMBOLS]
    if extra:
        problems.append(f'symbol_map に12銘柄でない名前がある: {extra}')
    return broker, smap, problems


def _merged(intervals):
    out = []
    for lo, hi in sorted(intervals):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def contact_missing(prev, cur):
    """第1段の接触の申告（prev。第1段の結果に書いたもの）のうち、第2段の記録（cur）で覆われていないもの。
    excluded は第2段でも excluded に、partial は partial か excluded（あとで fusion 系を見たと分かった場合）に入っていればよい。
    同じ銘柄か "*" の記録の期間の和で覆われていれば、書き方（区切り方）が変わってもよい"""
    out = []
    for key, keep in (('excluded', ('excluded',)), ('partial', ('partial', 'excluded'))):
        have = [e for k in keep for e in cur.get(k, [])]
        for raw in (prev or {}).get(key) or []:
            e = parse_period(raw)
            iv = _merged([(x['lo'], x['hi']) for x in have if x['symbol'] in (e['symbol'], '*')])
            if not any(lo <= e['lo'] and e['hi'] <= hi for lo, hi in iv):
                out.append(f"{key}: {e['symbol']} {e['from']}〜{e['to']}")
    return out


def ue_windows(infos, spec, contact):
    """§3.2 の期間と最低限の量: 銘柄ごとのエントリーを数える区間 [start, end)、除く銘柄、接触の申告で除いた日数、銘柄年。
    end は U-E の終わりと（最後の足＋1時間）の早い方。使える銘柄が8つ以上、かつ合計30銘柄年以上で ok"""
    ue_lo, ue_hi = day_range(*spec['ue'])
    late, drop = pd.Timestamp(spec['ue_late']), pd.Timestamp(spec['ue_drop'])
    rows = OrderedDict()
    for s, info in infos.items():
        first, last = info.get('first'), info.get('last')
        if first is None:
            rows[s] = OrderedDict(usable=False, reason='使える足がない')
            continue
        first, last = pd.Timestamp(first), pd.Timestamp(last)
        if first > drop:
            rows[s] = OrderedDict(usable=False, first=first, reason=f'最初の足 {first} が {drop.date()} より後なので除く')
            continue
        start = ue_lo if first <= late else max(ue_lo, first + pd.DateOffset(months=3))
        end = min(ue_hi, last + HOUR)
        ex = _merged([(max(e['lo'], start), min(e['hi'], end)) for e in contact['excluded']
                      if e['symbol'] in (s, '*') and min(e['hi'], end) > max(e['lo'], start)])
        ex_days = sum((hi - lo) / DAY for lo, hi in ex)
        days = max(0.0, (end - start) / DAY - ex_days) if end > start else 0.0
        rows[s] = OrderedDict(usable=days > 0, first=first, last=last, start=start, end=end,
                              excluded_days=ex_days, days=days, symbol_years=days / 365.25,
                              reason='' if days > 0 else 'エントリーを数える期間が残らない')
    usable = [s for s, r in rows.items() if r['usable']]
    total = float(sum(rows[s]['symbol_years'] for s in usable))
    ok = len(usable) >= spec['min_symbols'] and total >= spec['min_symyears']
    return OrderedDict(rows=rows, usable=usable, symbols=len(usable), symbol_years=total, ok=bool(ok),
                       min_symbols=spec['min_symbols'], min_symyears=spec['min_symyears'],
                       start=OrderedDict((s, rows[s]['start']) for s in usable))


# ---------------------------------------------------------------- ドライランの入力（開発データから作る。数値は無意味）
def write_komo_file(path, h1, sym):
    """NY+7 の仲値の H1 → komo135 の形（Date,open,high,low,close,tick_volume。Europe/Athens の時刻、Bid の整数価格）"""
    t = from_server(h1.index, {'kind': 'athens'})
    bid = h1[PRICE].to_numpy(float) - S_NOM[sym] / 2
    ints = np.round(bid * 10.0 ** DIGITS[sym])
    df = pd.DataFrame({'Date': t.strftime('%Y-%m-%d %H:%M:%S'), 'open': ints[:, 0], 'high': ints[:, 1],
                       'low': ints[:, 2], 'close': ints[:, 3], 'tick_volume': np.round(h1['Volume'].to_numpy(float))})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def write_mt5_file(path, h1, sym, clock):
    """NY+7 の仲値の H1 → MT5 の「バーをエクスポート」の形（タブ区切り、その時計の生の時刻、Bid）"""
    t = from_server(h1.index, clock)
    bid = h1[PRICE].to_numpy(float) - S_NOM[sym] / 2
    df = pd.DataFrame({'<DATE>': t.strftime('%Y.%m.%d'), '<TIME>': t.strftime('%H:%M:%S'),
                       '<OPEN>': bid[:, 0], '<HIGH>': bid[:, 1], '<LOW>': bid[:, 2], '<CLOSE>': bid[:, 3],
                       '<TICKVOL>': np.round(h1['Volume'].to_numpy(float)).astype(np.int64), '<VOL>': 0, '<SPREAD>': 0})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, sep='\t', index=False)


def dry_manifest(spec):
    """ドライラン用の仮の記録（実在の申告ではない）"""
    def per(sym, pool, at, frac, reason):
        lo, hi = day_range(*spec[pool])
        a = (lo + (hi - lo) * at).normalize()
        b = (lo + (hi - lo) * (at + frac)).normalize()
        return {'symbol': sym, 'from': str(a.date()), 'to': str(b.date()), 'reason': reason}
    syms = list(spec['dry_alias'])
    return {
        'contact': {
            'asked_on': 'ドライラン', 'summary': 'ドライラン用の仮の申告。実在の確認ではない',
            'excluded': [per(syms[0], 'ud', 0.6, 0.08, '仮: fusion 系を見た（U-D）'),
                         per(syms[1], 'ue', 0.3, 0.08, '仮: fusion 系を見た（U-E）')],
            'partial': [per('*', 'ud', 0.15, 0.08, '仮: 覚えていない'),
                        per(syms[2], 'ue', 0.1, 0.08, '仮: 旧 EA の通知')]},
        'broker': {'name': '（ドライラン）開発データから作った合成', 'server': '—', 'account_type': 'demo', 'exported_on': '—'},
        'symbol_map': {s: (f'{s}.dry' if s in spec['dry_alias'] else
                           {'broker_symbol': None, 'reason': 'ドライランでは開発データにない'}) for s in SYMBOLS},
    }


def make_dry_inputs(dev_dir, dst, spec, stage, log=print):
    """ドライランの入力を開発データ（<銘柄>_H1.csv、NY+7 の仲値）から作る:
      komo/<銘柄>/<銘柄>h1.csv  komo135 の形。新しい5銘柄は、開発データの別の銘柄に名前を付け替えたもの（spec['dry_alias']）
      ref_trades.csv.gz         v1.0（fusion）を開発データで直接走らせた取引のうち、データ源の照合の期間のもの
                                （final_eval_trades_main.csv.gz と同じ形。config=fusion、pool=U-B）
      mt5/<銘柄>_H1.csv         第2段だけ。MT5 の書き出しの形（spec['mt5_clock'] の時計の生の時刻）
      manifest.json             仮の記録"""
    alias = spec['dry_alias']
    full = OrderedDict()
    for sym, src in alias.items():
        if src not in full:
            full[src] = fd.load_prepared(src, 'H1', dev_dir)
    lo, hi = day_range(*spec['komo_clip'])
    dev = OrderedDict((s, h[(h.index >= lo) & (h.index < hi)]) for s, h in full.items())
    komo_dir = os.path.join(dst, 'komo')
    for sym, src in alias.items():
        write_komo_file(os.path.join(komo_dir, sym, f'{sym}h1.csv'), dev[src], sym)
    # データ源の照合の「v1.0 の取引」の代わり（開発データの v1.0 を直接走らせる）
    a, b = day_range(*spec['src_check'])
    rows = []
    for sym in [s for s in USED if s in alias and alias[s] == s]:
        tr, _ = fs.run_h1(dev[sym], sym)
        for t in tr:
            if a <= t['entry_time'] < b:
                rows.append(dict(config='fusion', pool='U-B', half='', symbol=sym, entry_time=t['entry_time'],
                                 exit_time=t['exit_time'], direction=t['direction'], entry=t['entry'],
                                 initial_sl=t['initial_sl'], pnl_r=t['pnl_r'], exit_reason=t['exit_reason'],
                                 bars_held=t['bars_held'], m_score=t['m_score']))
    ref = os.path.join(dst, 'ref_trades.csv.gz')
    with open(ref, 'wb') as raw, gzip.GzipFile(filename='ref_trades.csv', mode='wb', fileobj=raw, mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding='utf-8', newline='') as w:
            pd.DataFrame(rows, columns=['config', 'pool', 'half', 'symbol', 'entry_time', 'exit_time', 'direction',
                                        'entry', 'initial_sl', 'pnl_r', 'exit_reason', 'bars_held', 'm_score']).to_csv(
                w, index=False, date_format='%Y-%m-%d %H:%M:%S', lineterminator='\n')
    out = dict(komo_dir=komo_dir, ref_trades=ref, manifest=dry_manifest(spec), mt5_dir=None)
    if stage == 2:
        mlo, mhi = day_range(*spec['mt5_clip'])
        clock = {'kind': spec['mt5_clock'], 'hours': 0}
        mt5_dir = os.path.join(dst, 'mt5')
        for sym, src in alias.items():
            h = full[src]
            write_mt5_file(os.path.join(mt5_dir, f'{sym}_H1.csv'), h[(h.index >= mlo) & (h.index < mhi)], sym, clock)
        out['mt5_dir'] = mt5_dir
    with open(os.path.join(dst, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(out['manifest'], f, ensure_ascii=False, indent=1)
    log(f'[v11_eval] ドライランの入力を作った: {dst}（開発データ {dev_dir} の {"・".join(dev)}。'
        f'新しい5銘柄は名前を付け替えたもの: ' + '、'.join(f'{s}←{a}' for s, a in alias.items() if s != a) + '）')
    return out


# ---------------------------------------------------------------- 実行（系列ごと・構成ごとに1回だけ）
_CTX = {}


def _init(ctx):
    """仕事を走らせるプロセスの初期化（§12）: 表に3銘柄・5銘柄を足し、読み込みの設定を覚える。戻り値は元に戻す関数"""
    _CTX.clear()
    _CTX.update(ctx)
    _CTX['cache'] = {}
    return install_tables()


def _init_worker(ctx):
    restore = _init(ctx)
    mp_util.Finalize(None, restore, exitpriority=10)       # 子プロセスが終わるときに元に戻す


def _series(src, sym):
    key = (src, sym)
    cache = _CTX['cache']
    if key not in cache:
        if src == 'komo':
            df, _ = load_komo(_CTX['komo'][sym], sym, _CTX.get('komo_clip'))
        elif src == 'mt5':
            df, _ = load_mt5(_CTX['mt5'][sym], sym, _CTX['clock'], _CTX['mt5_clip'])
        else:
            raise KeyError(src)
        cache[key] = df
    return cache[key]


def to_frame(trades, sym, src):
    df = pd.DataFrame(trades)
    if df.empty:
        df = pd.DataFrame({c: pd.Series(dtype=float) for c in BASE_COLS})
        df['entry_time'] = pd.Series(dtype='datetime64[ns]')
        df['exit_time'] = pd.Series(dtype='datetime64[ns]')
        df['exit_reason'] = pd.Series(dtype=object)
    df['symbol'] = sym
    df['src'] = src
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    for c in ('entry', 'initial_sl', 'risk', 'pnl_r', 'mfe_r', 'mae_r'):
        df[c] = df[c].astype(float)
    df['direction'] = df['direction'].astype(np.int64)
    df['bars_held'] = df['bars_held'].astype(np.int64)
    df['seq'] = np.arange(len(df), dtype=np.int64)
    df['sym_i'] = SYMBOLS.index(sym)
    df['src_i'] = SRC_ORDER[src]
    return df


def _job(job):
    """job = (系列の出どころ komo / mt5, 銘柄, 構成, 切断日 or None)。戻り値 (job, 取引, 理由コード別件数, 足の情報, (経過秒, CPU秒))"""
    src, sym, cfg, cut = job
    t0, c0 = time.perf_counter(), time.process_time()
    h1 = _series(src, sym)
    if cut is not None:
        h1 = h1[h1.index < pd.Timestamp(cut)]
    info = dict(bars=int(len(h1)), first=h1.index[0], last=h1.index[-1])
    sw = switches(cfg)
    with job_tables(src, sym, cfg):
        trades, funnel = fs.run_h1(h1, sym, sw)
    df = to_frame(trades, sym, src)
    info['trades_all'] = int(len(df))
    keep = (_CTX.get('naive_from') or {}).get(src) if is_naive(cfg) else None
    if keep is not None:                                    # 素朴ベースラインは判定プールの始まり以降だけ持ち帰る（seq は全体の番号のまま）
        df = df[df['entry_time'] >= pd.Timestamp(keep)].reset_index(drop=True)
    return job, df, dict(funnel), info, (time.perf_counter() - t0, time.process_time() - c0)


def job_tag(job):
    src, sym, cfg, cut = job
    return f'{src:<4} {sym} {cfg}' + (f'（{cut} で切断）' if cut else '')


class Runner:
    """仕事を並列に走らせる（spawn）。workers<=1 は同じプロセスで走らせ、終わったら表を元に戻す"""

    def __init__(self, ctx, workers, log):
        self.ctx, self.workers, self.log = ctx, workers, log
        self.pool = None
        self.restore = None
        self.cpu = 0.0

    def __enter__(self):
        if self.workers <= 1:
            self.restore = _init(self.ctx)
        else:
            self.pool = mp.get_context('spawn').Pool(self.workers, initializer=_init_worker, initargs=(self.ctx,))
        return self

    def __exit__(self, et, ev, tb):
        if self.pool is not None:
            if et is None:
                self.pool.close()
            else:
                self.pool.terminate()                       # 残りの仕事を待たずに止める
            self.pool.join()
        if self.restore is not None:
            self.restore()
            _CTX.clear()
        return False

    def run(self, jobs, label=''):
        out = {}
        t0 = time.perf_counter()
        it = map(_job, jobs) if self.pool is None else self.pool.imap_unordered(_job, jobs, chunksize=1)
        for k, (job, df, funnel, info, (sec, csec)) in enumerate(it, 1):
            out[job] = (df, funnel, info)
            self.cpu += csec
            kept = f'（全{info["trades_all"]}件）' if info.get('trades_all', len(df)) != len(df) else ''
            self.log(f'[{label}{k:>5}/{len(jobs)}] {job_tag(job):<40} {len(df):>6}件{kept} {sec:6.1f}秒'
                     f'（CPU {csec:5.1f}秒）  経過 {time.perf_counter() - t0:6.0f}秒')
        return out


def check_infos(out, infos, src):
    """仕事が使った系列（足の数・最初・最後）が、実行前に読み込んだ記録と同じか（読み込みは決定的なので同じはず）"""
    for (s_, sym, cfg, cut), (_, _, info) in out.items():
        if s_ != src or cut is not None:
            continue
        rec = infos[sym]
        if (info['bars'], info['first'], info['last']) != (rec['bars'], rec['first'], rec['last']):
            raise RuntimeError(f'{src} {sym}: 仕事の足 {info} が実行前の記録と違う')


def chrono(df):
    if len(df) == 0:
        return df
    return df.sort_values(['entry_time', 'src_i', 'sym_i', 'seq'], kind='mergesort').reset_index(drop=True)


def gather(out, cfgs, srcs=('komo', 'mt5')):
    """{job: (取引, …)} → {構成: 全系列の取引（切断テストを除く）}"""
    T = OrderedDict()
    for c in cfgs:
        parts = [df for (s_, sym, c_, cut), (df, _, _) in sorted(out.items(), key=lambda kv: (
            SRC_ORDER[kv[0][0]], SYMBOLS.index(kv[0][1]))) if c_ == c and cut is None and s_ in srcs]
        nonempty = [p for p in parts if len(p)]
        if nonempty:
            T[c] = pd.concat(nonempty, ignore_index=True) if len(nonempty) > 1 else nonempty[0].copy()
        elif parts:
            T[c] = parts[0].copy()
    return T


# ---------------------------------------------------------------- プールへの振り分け（§4）
def exit_bar(df):
    """決済の足: 決済理由が WEEKEND・END なら exit_time − 1時間（確定時刻で記録しているため）、それ以外は exit_time"""
    t = pd.DatetimeIndex(df['exit_time'])
    last = df['exit_reason'].astype(str).str.split('+').str[-1].to_numpy(dtype=object)
    shift = np.isin(last, ['WEEKEND', 'END'])
    return t.where(~shift, t - HOUR)


def chf_rule(df):
    """§4: USDCHF・EURCHF で entry_time < 2015-01-16 00:00、かつ決済の足 ≥ 2015-01-15 00:00（保有期間が 2015-01-15 を含む）"""
    if len(df) == 0:
        return np.zeros(0, dtype=bool)
    et = pd.DatetimeIndex(df['entry_time'])
    xb = exit_bar(df)
    return np.asarray(np.isin(df['symbol'].to_numpy(dtype=object), CHF) & (et < CHF_ENTRY_BEFORE) & (xb >= CHF_EXIT_FROM))


def assign(df, spec, contact=None, ue_start=None):
    """取引に pool（U-D・U-X・U-E・''）・half（U-D・U-E の前半／後半）・contact（excluded／partial／''）・
    ue_after（U-E後）・chf_excl（U-X の CHF の除外）・src_check（データ源の照合の期間）・year を付ける。
    komo135 の系列は U-D・U-X、利用者の系列（mt5）は U-E。ue_start: {銘柄: エントリーを数え始める時刻}（使える銘柄だけ）"""
    out = df.copy()
    n = len(out)
    src = out['src'].to_numpy(dtype=object)
    sym = out['symbol'].to_numpy(dtype=object)
    et = pd.DatetimeIndex(out['entry_time'])
    komo, mt5 = src == 'komo', src == 'mt5'
    pool = np.full(n, '', dtype=object)

    def put(m, name):
        m = np.asarray(m, dtype=bool)
        if np.any(m & (pool != '')):
            raise ValueError('評価プールが重なっている')
        pool[m] = name

    lo, hi = day_range(*spec['ud'])
    put(komo & np.isin(sym, SYMBOLS) & (et >= lo) & (et < hi), 'U-D')
    lo, hi = day_range(*spec['ux'])
    for s in NEW:
        a = max(lo, pd.Timestamp(spec['ux_from'].get(s, spec['ux'][0])))
        put(komo & (sym == s) & (et >= a) & (et < hi), 'U-X')
    ue_hi = day_range(*spec['ue'])[1]
    for s, a in (ue_start or {}).items():
        put(mt5 & (sym == s) & (et >= pd.Timestamp(a)) & (et < ue_hi), 'U-E')
    half = np.full(n, '', dtype=object)
    for p, mid in pool_midpoints(spec).items():
        m = pool == p
        half[m & (et < mid)] = '前半'
        half[m & (et >= mid)] = '後半'
    flag = np.full(n, '', dtype=object)
    judged = np.isin(pool, JUDGE_POOLS)
    for kind in ('partial', 'excluded'):                   # 両方に当たる取引は excluded（判定から除く）を優先する
        for e in (contact or {}).get(kind, []):
            m = judged & ((sym == e['symbol']) | (e['symbol'] == '*')) & (et >= e['lo']) & (et < e['hi'])
            flag[np.asarray(m, dtype=bool)] = kind
    a_lo = day_range(*spec['ue_after'])[0]
    c_lo, c_hi = day_range(*spec['src_check'])
    out['pool'] = pool
    out['half'] = half
    out['contact'] = flag
    out['ue_after'] = ((pool == 'U-E') & (et >= a_lo)).astype(np.int64)
    out['chf_excl'] = ((pool == 'U-X') & chf_rule(out)).astype(np.int64)
    out['src_check'] = (komo & np.isin(sym, USED) & (et >= c_lo) & (et < c_hi)).astype(np.int64)
    out['year'] = np.asarray(et.year, dtype=np.int64)
    return out


def judge_frame(d):
    """判定プール（U-D＋U-E）から、接触の申告で除いた取引を除いたもの"""
    return d[d['pool'].isin(JUDGE_POOLS) & (d['contact'] != 'excluded')]


# ---------------------------------------------------------------- 統計（§8・§9）
def finite(x):
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def nse(df):
    """取引数・平均R・標準誤差（ddof=1）だけ（第1段で出すもの §7）"""
    r = df['pnl_r'].to_numpy(dtype=float)
    n = len(r)
    sd = float(np.std(r, ddof=1)) if n > 1 else NAN
    return OrderedDict(trades=int(n), avg_r=float(r.mean()) if n else NAN, se=sd / math.sqrt(n) if n > 1 else NAN)


def stop_rule(ud):
    """§7: v1.1 の U-D の平均R ≤ 0 なら不合格（第1段で打ち切り）。平均が求まらない（取引0回）ときも打ち切り"""
    avg = ud['avg_r']
    stop = not (finite(avg) and avg > 0)
    return OrderedDict(stop=bool(stop), verdict='不合格（第1段で打ち切り）' if stop else '継続（利用者に第2段のデータを依頼する）',
                       trades=ud['trades'], avg_r=avg, se=ud['se'], rule='v1.1 の U-D の平均R ≤ 0 なら打ち切り')


def by(df, key, order=None):
    out = OrderedDict()
    if len(df) == 0:
        return out
    vals = list(order) if order is not None else sorted(df[key].dropna().unique())
    for v in vals:
        lab = str(int(v)) if isinstance(v, (int, np.integer)) else str(v)
        out[lab] = fe.summary(df[df[key] == v])
    return out


def choose_naive_p(mean_counts, target, tol=NAIVE_TOL):
    """§6: 判定プールでの20シードの取引数の平均が、v1.1 の判定プールの取引数に最も近い p（同じ近さなら小さい p）"""
    ps = sorted(mean_counts)
    best = min(ps, key=lambda p: (abs(mean_counts[p] - target), p))
    m = float(mean_counts[best])
    return OrderedDict(p=best, mean_count=m, target=int(target), ratio=m / target if target > 0 else NAN,
                       within_tol=bool(target > 0 and abs(m - target) <= tol * target), tol=tol)


def judge_p2(pool_avg, sym_stats):
    """P2: U-D と U-E の両方で平均R＞0（取引0回のプールは満たさない）。かつ判定プールで30回以上の銘柄の60%以上で平均R＞0"""
    pos_pools = [p for p in JUDGE_POOLS if finite(pool_avg.get(p)) and pool_avg[p] > 0]
    elig = [s for s, (n, a) in sym_stats.items() if n >= P2_MIN_N]
    pos = [s for s in elig if finite(sym_stats[s][1]) and sym_stats[s][1] > 0]
    frac = len(pos) / len(elig) if elig else NAN
    ok = len(pos_pools) == len(JUDGE_POOLS) and bool(elig) and frac >= P2_FRAC
    return OrderedDict(ok=bool(ok), pools_positive=pos_pools, pool_avg=OrderedDict(pool_avg), eligible_symbols=elig,
                       positive_symbols=pos, frac=frac)


def judge_p4(avg, seed_avgs):
    """P4: v1.1 の平均R ≥ 素朴（20シードの平均R の平均）＋0.10R、かつ20シードの平均R の95パーセンタイルを上回る"""
    a = np.asarray([x for x in seed_avgs if finite(x)], dtype=float)
    if len(a) == 0 or len(a) != len(seed_avgs):
        return OrderedDict(ok=False, v11_avg=avg, naive_mean=NAN, naive_p95=NAN, margin=P4_MARGIN,
                           note='素朴ベースラインの平均Rが計算できないシードがある')
    mean, p95 = float(a.mean()), float(np.percentile(a, 95))
    ok = finite(avg) and avg >= mean + P4_MARGIN and avg > p95
    return OrderedDict(ok=bool(ok), v11_avg=avg, naive_mean=mean, naive_p95=p95, margin=P4_MARGIN, need=mean + P4_MARGIN)


def psr_block(J, months):
    """P6: PSR＝Φ( SR̂·√(T−1) ÷ √(1 − γ₃·SR̂ + (γ₄−1)/4·SR̂²) )。final_eval.deflated_sharpe に SR₀＝0 を渡す。
    系列は判定プールの月次R（取引のない月は0）"""
    x = fe.monthly_r(J, *months)
    arr = x.to_numpy(dtype=float)
    sr = fe.sharpe(arr)
    g3, g4 = fe.moments(arr)
    p = fe.deflated_sharpe(sr, len(arr), g3, g4, 0.0)
    return OrderedDict(ok=bool(finite(p) and p >= P6_MIN), psr=p, threshold=P6_MIN, T=int(len(arr)),
                       mean=float(arr.mean()) if len(arr) else NAN,
                       sd=float(np.std(arr, ddof=1)) if len(arr) > 1 else NAN, sr=sr, skew=g3, kurt=g4, sr0=0.0,
                       months=list(months), monthly_r=OrderedDict((str(k), float(v)) for k, v in x.items()))


def gap_block(J, syms):
    """GAP_FALLBACK の件数（FX は XAUUSD 以外の11銘柄）"""
    gap = J['exit_reason'].astype(str).str.contains('GAP_FALLBACK', regex=False).to_numpy()
    sym = J['symbol'].to_numpy(dtype=object)
    fx = gap & np.isin(sym, FX)
    years = J['year'].to_numpy()
    return OrderedDict(total=int(gap.sum()), fx=int(fx.sum()),
                       by_symbol=OrderedDict((s, int((gap & (sym == s)).sum())) for s in syms),
                       fx_by_year=OrderedDict((str(int(y)), int((fx & (years == y)).sum())) for y in sorted(set(years[fx]))))


def warn_long_short(long_avg, short_avg):
    fire = finite(long_avg) and finite(short_avg) and ((long_avg < 0) != (short_avg < 0))
    return OrderedDict(fire=bool(fire), long_avg=long_avg, short_avg=short_avg)


def warn_gap(fx_count, years):
    rate = fx_count / years if years > 0 else NAN
    return OrderedDict(fire=bool(finite(rate) and rate > GAP_PER_YEAR_MAX), fx_count=int(fx_count), years=years,
                       per_year=rate)


def warn_ten_month(mean10):
    return OrderedDict(fire=bool(finite(mean10) and mean10 < TEN_MONTH_MIN), mean=mean10, threshold=TEN_MONTH_MIN)


def ten_month(df, segments):
    """連続10か月窓の回数（v1.0 と同じ考え方）。segments: [(開始, 終了の翌日)]。区間に丸ごと入る暦月だけで窓を作り、
    つながった区間は1本にまとめる"""
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
    return OrderedDict(mean=float(np.mean(wins)) if wins else NAN, min=int(min(wins)) if wins else None,
                       max=int(max(wins)) if wins else None, windows=len(wins), full_months=months_used,
                       trades=int(len(df)))


def delta(a, b):
    """a − b の平均R差と標準誤差 √(SE_a²+SE_b²)"""
    d = a['avg_r'] - b['avg_r'] if finite(a['avg_r']) and finite(b['avg_r']) else NAN
    se = math.sqrt(a['se'] ** 2 + b['se'] ** 2) if finite(a['se']) and finite(b['se']) else NAN
    return OrderedDict(delta=d, se=se, z=d / se if finite(d) and finite(se) and se > 0 else NAN)


# ---------------------------------------------------------------- データ源の照合・切断テスト（§4・§9）
def load_ref_trades(path, config='fusion', pool='U-B'):
    """v1.0 の OANDA 版の取引（final_eval_trades_main.csv.gz の config・pool）"""
    d = pd.read_csv(path, keep_default_na=False)
    d = d[(d['config'] == config) & (d['pool'] == pool)].copy()
    d['entry_time'] = pd.to_datetime(d['entry_time'])
    d['exit_time'] = pd.to_datetime(d['exit_time'])
    d['direction'] = d['direction'].astype(np.int64)
    d['pnl_r'] = d['pnl_r'].astype(float)
    return d.reset_index(drop=True), OrderedDict(file=os.path.basename(path), sha256=sha256_of(path), config=config,
                                                 pool=pool, rows=int(len(d)))


def _near_matches(a, b, tol=HOUR):
    """同じ銘柄・方向で、エントリー時刻の差が tol 以内のものを1対1で対応づけた件数（早い順に貪欲に）"""
    n = 0
    for (s, d), g in b.groupby(['symbol', 'direction']):
        pool = sorted(a.loc[(a['symbol'] == s) & (a['direction'] == d), 'entry_time'])
        used = [False] * len(pool)
        for t in sorted(g['entry_time']):
            for i, u in enumerate(pool):
                if not used[i] and abs(u - t) <= tol:
                    used[i] = True
                    n += 1
                    break
    return n


def source_check(komo_fusion, ref, spec, syms):
    """§9 のデータ源の照合: 使用済み7銘柄の照合期間に入った、komo135 版の fusion の取引と v1.0 の OANDA 版の取引の、
    件数・エントリー（銘柄・方向・時刻）の一致率（一致件数 ÷ 多い方の件数）・平均R"""
    lo, hi = day_range(*spec['src_check'])
    use = [s for s in USED if s in syms]

    def window(d):
        et = pd.DatetimeIndex(d['entry_time'])
        return d[np.isin(d['symbol'].to_numpy(dtype=object), use) & (et >= lo) & (et < hi)]
    a = window(komo_fusion[komo_fusion['src'] == 'komo'])
    b = window(ref)

    def keys(d):
        return set(zip(d['symbol'], d['direction'].astype(int), pd.DatetimeIndex(d['entry_time'])))

    def block(x, y):
        m = len(keys(x) & keys(y))
        big = max(len(x), len(y))
        return OrderedDict(komo=int(len(x)), oanda=int(len(y)), matched=int(m), rate=m / big if big else NAN,
                           rate_vs_oanda=m / len(y) if len(y) else NAN, rate_vs_komo=m / len(x) if len(x) else NAN,
                           near_matched=int(_near_matches(x, y)),
                           avg_r_komo=float(x['pnl_r'].mean()) if len(x) else NAN,
                           avg_r_oanda=float(y['pnl_r'].mean()) if len(y) else NAN)
    out = block(a, b)
    out['near_rate'] = out['near_matched'] / max(len(a), len(b)) if max(len(a), len(b)) else NAN
    out['window'] = list(spec['src_check'])
    out['symbols'] = use
    out['by_symbol'] = OrderedDict((s, block(a[a['symbol'] == s], b[b['symbol'] == s])) for s in use)
    return out


TRUNC_KEYS = ['entry_time', 'direction', 'entry', 'initial_sl', 'exit_time', 'pnl_r', 'exit_reason', 'bars_held']


def truncation_check(full, part, cut, part_info, sym):
    """§4: 切った系列と全期間の系列とで、切った時刻より前に決済した取引が全件一致するか"""
    c = pd.Timestamp(cut)
    a = full[full['exit_time'] < c][TRUNC_KEYS].reset_index(drop=True)
    b = part[part['exit_time'] < c][TRUNC_KEYS].reset_index(drop=True)
    same = len(a) == len(b) and all(a[k].tolist() == b[k].tolist() for k in TRUNC_KEYS)
    return OrderedDict(symbol=sym, config=MAIN, cut=c, last_bar=part_info['last'], compared=int(len(a)),
                       match=bool(same), full_trades=int(len(full)), cut_trades=int(len(part)))


# ---------------------------------------------------------------- 出力
def clean(o):
    """JSON 用（NaN→null、±inf→文字列、numpy・Timestamp→素の型）"""
    if isinstance(o, dict):
        return OrderedDict((str(k), clean(v)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, np.integer):
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
    if isinstance(o, pd.Timedelta):
        return _hours(o)
    if isinstance(o, pd.Period):
        return str(o)
    return o


def trade_cols(frames):
    extra = []
    for d in frames:
        extra += [k for k in d.columns if k.startswith('m_') and k not in extra]
    return FLAG_COLS + BASE_COLS + extra


def ordered(d, cfg):
    return d.sort_values(['src_i', 'sym_i', 'seq'], kind='mergesort').assign(config=cfg)


def write_trades(path, T, cfgs):
    """取引一覧を1つの CSV（gzip、時刻0で毎回同じバイト列）に書く。並びは構成 → 出どころ → 銘柄 → 発生順"""
    frames = [ordered(T[c], c) for c in cfgs if c in T]
    cols = trade_cols(frames)
    name = os.path.basename(path)[:-3] if path.endswith('.gz') else os.path.basename(path)
    with open(path, 'wb') as raw, gzip.GzipFile(filename=name, mode='wb', fileobj=raw, mtime=0) as gz:
        with io.TextIOWrapper(gz, encoding='utf-8', newline='') as w:
            if not frames:
                w.write(','.join(cols) + '\n')
            for i, d in enumerate(frames):
                d.reindex(columns=cols).to_csv(w, index=False, header=(i == 0), date_format='%Y-%m-%d %H:%M:%S',
                                               lineterminator='\n')
    return OrderedDict(file=os.path.basename(path), sha256=sha256_of(path),
                       rows=int(sum(len(d) for d in frames)), configs=[c for c in cfgs if c in T])


def text_rows(df, cols):
    """取引を CSV と同じ書き方の文字列にする（第1段の一覧と比べるため）"""
    buf = io.StringIO()
    df.reindex(columns=cols).to_csv(buf, index=False, date_format='%Y-%m-%d %H:%M:%S', lineterminator='\n')
    buf.seek(0)
    return pd.read_csv(buf, dtype=str, keep_default_na=False)


def _same_rows(x, y):
    """文字列にした取引の表どうしが全件一致するか。違えば最初の食い違い"""
    x, y = x.reset_index(drop=True), y.reset_index(drop=True)
    same = len(x) == len(y) and (len(x) == 0 or x.equals(y))     # 0件どうしは列の型によらず一致
    first = None
    if not same:
        for i in range(min(len(x), len(y))):
            if not x.iloc[i].equals(y.iloc[i]):
                first = OrderedDict(row=i, stage1=x.iloc[i].to_dict(), stage2=y.iloc[i].to_dict())
                break
        if first is None:
            first = OrderedDict(row=min(len(x), len(y)), note='件数が違う')
    return OrderedDict(stage1=int(len(x)), stage2=int(len(y)), match=bool(same), first_difference=first)


def compare_with_stage1(path, T, spec):
    """第1段の取引一覧（komo135 の3構成）と、第2段で走らせ直した取引の照合（§7.2）。列は CMP_COLS（プールの印は比べない）。
    gate: 第1段の U-D の v1.1 の取引一覧が全件一致するか（違えば判定しない）。configs: 3構成の全取引（違いは逸脱として記録する）"""
    a = pd.read_csv(path, dtype=str, keep_default_na=False)
    a = a[a['src'] == 'komo'].reset_index(drop=True)
    empty = pd.DataFrame(columns=CMP_COLS)
    rows = OrderedDict()
    for c in CONFIGS:
        d = T.get(c)
        y = text_rows(ordered(d[d['src'] == 'komo'], c), CMP_COLS) if d is not None else empty
        rows[c] = _same_rows(a[a['config'] == c][CMP_COLS], y)
    d = T.get(MAIN)
    if d is not None:
        d = assign(d[d['src'] == 'komo'], spec)                # プールの印だけを付け直す（komo135 のプールは記録によらない）
        y = text_rows(ordered(d[d['pool'] == 'U-D'], MAIN), CMP_COLS)
    else:
        y = empty
    gate = _same_rows(a[(a['config'] == MAIN) & (a['pool'] == 'U-D')][CMP_COLS], y)
    return OrderedDict(all_match=bool(all(r['match'] for r in rows.values())), gate_ok=gate['match'],
                       gate=gate, configs=rows)


def _git(*a):
    try:
        r = subprocess.run(['git', *a], cwd=ROOT, capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def git_state():
    git = _git
    changed = git('diff', '--name-only', 'HEAD', '--', 'fusion')
    untracked = git('ls-files', '--others', '--exclude-standard', '--', 'fusion')
    dirty = git('status', '--porcelain', '--untracked-files=all', '--', *EVAL_FILES)
    tracked = git('ls-files', '--', *EVAL_FILES)
    tracked = set(tracked.split('\n')) if tracked else set()
    return OrderedDict(commit=git('rev-parse', 'HEAD'), prereg_commit=git('log', '-1', '--format=%H', '--', PREREG),
                       eval_files=list(EVAL_FILES),
                       modified_in_fusion=changed.split('\n') if changed else [],
                       untracked_in_fusion=untracked.split('\n') if untracked else [],
                       eval_files_dirty=(None if dirty is None else [ln.strip().split(None, 1)[-1]
                                                                     for ln in dirty.split('\n') if ln.strip()]),
                       eval_files_untracked=[f for f in EVAL_FILES if f not in tracked])


def git_problems(g):
    """本番で止める理由（実行したコードと事前登録をコミットのハッシュで特定できない）"""
    out = []
    if not g.get('commit'):
        out.append('git のコミットのハッシュが取れない（§13 で記載が必要）')
    if not g.get('prereg_commit'):
        out.append('事前登録（' + PREREG + '）を変えたコミットが取れない')
    if g.get('eval_files_dirty') is None:
        out.append('git status が取れない')
    elif g['eval_files_dirty']:
        out.append('評価に使うファイルに未コミットの変更がある: ' + '、'.join(g['eval_files_dirty']))
    if g.get('eval_files_untracked'):
        out.append('評価に使うファイルが git に登録されていない: ' + '、'.join(g['eval_files_untracked']))
    return out


def prereg_problems(path=None):
    """本番で止める理由（事前登録がまだ凍結されていない）。凍結するときに冒頭の「まだ凍結していない」の注記を消す約束（§13）"""
    path = path or os.path.join(ROOT, PREREG)
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        return [f'事前登録 {PREREG} が読めない（{e}）']
    if FROZEN_MARK in text:
        return [f'事前登録 {PREREG} に「{FROZEN_MARK}」の注記が残っている（凍結し、注記を消してコミットしてから実行する）']
    return []


def prereg_stage1_contact(path=None):
    """第1段で記録ファイルを渡さないときの §2 の確認の記録: 事前登録 §2 の「第1段の前の確認の結果（日付）」の項目。
    「除外も「一部汚れ」の記録もなし」と書かれているときだけ使う（除く銘柄×期間があるなら --manifest で渡す）。
    戻り値 (contact, 問題)"""
    path = path or os.path.join(ROOT, PREREG)
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().split('\n')
    except OSError as e:
        return None, [f'事前登録 {PREREG} が読めない（{e}）']
    for i, ln in enumerate(lines):
        m = STAGE1_CONTACT_RE.search(ln)
        if not m:
            continue
        para = [ln.strip()]
        for nxt in lines[i + 1:]:                              # 箇条書きの続きの行（字下げ2つ）まで
            if not nxt.startswith('  ') or nxt.lstrip().startswith('- ') or not nxt.strip():
                break
            para.append(nxt.strip())
        text = ''.join(para).replace('**', '').lstrip('- ').strip()
        if NO_CONTACT_MARK not in text:
            return None, [f'事前登録 §2 の第1段の前の確認の結果が「{NO_CONTACT_MARK}」でない'
                          '（除く銘柄×期間は --manifest の contact で渡す）']
        return OrderedDict(asked_on=m.group(1), summary=f'事前登録 {PREREG} §2 の記録：{text}', excluded=[], partial=[]), []
    return None, ['§2 の利用者への確認の記録がない（--manifest で渡すか、事前登録 §2 に「第1段の前の確認の結果（日付）」を書く）']


def deadline_problems(today=None):
    """第2段の期限（§7.2）。過ぎていれば第2段は行わない（v1.1 は「未決」のまま閉じる）"""
    d = pd.Timestamp(today if today is not None else pd.Timestamp.now()).normalize()
    if d > STAGE2_DEADLINE:
        return [f'第2段の期限 {STAGE2_DEADLINE.date()} を過ぎている（今日 {d.date()}）。v1.1 は「未決」のまま閉じる（§7.2）']
    return []


def code_changes_since(commit):
    """第1段を走らせたコミットから HEAD までに変わった、評価に使うファイル（git で確かめられなければ None）"""
    if not commit:
        return None
    out = _git('diff', '--name-only', commit, 'HEAD', '--', *EVAL_FILES)
    if out is None:
        return None
    return [ln for ln in out.split('\n') if ln.strip()]


class RunLog:
    """画面と run ログの両方に書く。実行前の確認が通るまでは貯めておき、ログのファイルを開いたときに書き出す"""

    def __init__(self, sink):
        self.sink = sink
        self.lines = []
        self.fh = None

    def __call__(self, s):
        self.sink(s)
        if self.fh is not None:
            self.fh.write(s + '\n')
            self.fh.flush()
        else:
            self.lines.append(s)

    def open(self, path, dry, rerun_reason):
        """本番: 前の実行のログ（結果のファイルができる前に失敗した実行）があれば、理由なしには走らせない。回数と理由を残す"""
        if not dry and os.path.exists(path):
            if not rerun_reason:
                raise SystemExit(f'[v11_eval] 前の実行のログ {path} がある（結果のファイルができる前に失敗した実行）。'
                                 '走らせ直すときは --rerun-reason に理由を書く（§13：回数と理由をログに残す）')
            with open(path, encoding='utf-8') as f:
                k = sum(1 for ln in f if ln.startswith('=== 実行 第')) + 1
            self.fh = open(path, 'a', encoding='utf-8')
            self.fh.write(f'\n=== 実行 第{k}回（走らせ直し。理由: {rerun_reason}） ===\n')
        else:
            self.fh = open(path, 'w', encoding='utf-8')
            self.fh.write('=== ドライラン（数値は無意味） ===\n' if dry else '=== 実行 第1回 ===\n')
        for s in self.lines:
            self.fh.write(s + '\n')
        self.lines = []
        self.fh.flush()

    def close(self):
        if self.fh is not None:
            self.fh.close()
            self.fh = None


def shown_path(p, out_dir):
    """記録に書くパス（出力フォルダの中なら相対。ドライランの結果を出力先によらず同じにするため）"""
    if p is None:
        return None
    ap, ao = os.path.abspath(p), os.path.abspath(out_dir)
    if ap == ao:
        return '.'
    return './' + os.path.relpath(ap, ao).replace(os.sep, '/') if ap.startswith(ao + os.sep) else ap


def _prepare_out(out_dir, stage, dry):
    res = os.path.join(out_dir, f'stage{stage}_results.json')
    if not dry and os.path.exists(res):
        raise SystemExit(f'[v11_eval] {res} がすでにある。各段の評価は1回だけ（§13）なので走らせ直さない')
    os.makedirs(out_dir, exist_ok=True)


def _write_json(path, obj):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(clean(obj), fh, ensure_ascii=False, indent=1, allow_nan=False)
        fh.write('\n')


def komo_problems(info, sym, spec):
    """本番の komo135 のファイルの確認（§3.1。違えば事前登録したデータではないので止める）"""
    out = []
    if spec.get('komo_rows') and info['rows'] != spec['komo_rows']:
        out.append(f"{sym}: 行数 {info['rows']} が事前登録の {spec['komo_rows']} と違う")
    if spec.get('komo_last') and info['raw_last'] != pd.Timestamp(spec['komo_last']):
        out.append(f"{sym}: 最終の足 {info['raw_last']} が事前登録の {spec['komo_last']} と違う")
    if not info['int_check']:
        out.append(f"{sym}: 価格が 10^−{info['digits']} の整数倍になっていない（最大のずれ {info['int_check_max_dev']}）")
    if info['raw_fraction_values'] > 2 * info['rows']:              # 4本値の半分を超える
        out.append(f"{sym}: 生の価格の大半が整数でない（{info['raw_fraction_values']}個）。komo135 の整数の形式ではない")
    if spec.get('ux_first_by') and sym in NEW and (info['server_first'] is None
                                                    or info['server_first'] > pd.Timestamp(spec['ux_first_by'])):
        out.append(f"{sym}: 最初の足 {info['server_first']} が {spec['ux_first_by']} より後（U-X のウォームアップが3か月ない）")
    return out


def _start(spec, dry, log, stage, out_dir):
    log(f'[v11_eval] 第{stage}段' + ('のドライラン：数値は無意味（開発データの中に作った仮のプールで、コードの通り道だけを確かめる）'
                                    if dry else '（本番。事前登録 ' + PREREG + ' のとおりに1回だけ）'))
    pool_midpoints(spec)                                       # 中点が事前登録の値と合うことを先に確かめる
    _prepare_out(out_dir, stage, dry)


def _load_komo_all(komo_dir, spec, dry, problems, log):
    files = find_komo_files(komo_dir, spec['symbols'])
    missing = [s for s in spec['symbols'] if s not in files]
    if missing and not dry:
        problems.append('komo135 のファイルがない銘柄: ' + '、'.join(missing))
    infos = OrderedDict()
    for s, p in files.items():
        try:
            _, info = load_komo(p, s, spec['komo_clip'])
        except Exception as e:                                 # 読めない・時刻の換算で例外 → 何も計算しないうちに止める
            problems.append(f'{p}: 読み込みに失敗（{type(e).__name__}: {e}）')
            continue
        info['path'] = os.path.relpath(p, komo_dir).replace(os.sep, '/')
        infos[s] = info
        if not dry:
            problems += komo_problems(info, s, spec)
        log(f"[v11_eval] komo135 {s}: {info['file']} {info['rows']}行 → {info['bars']}本 "
            f"{info['first']}〜{info['last']}（NY+7）SHA-256 {info['sha256'][:12]}…")
    return files, infos, missing


def _meta_common(spec, gstate, contact, komo_dir, infos, missing, out_dir, stage, dev_dir):
    return OrderedDict(
        title=f'FUSION-CORE v1.1 評価 第{stage}段（PREREGISTRATION_v1_1.md）', stage=stage, dry_run=bool(spec['dry_run']),
        note=('ドライラン：数値は無意味。開発データ（2013〜2017）の中に作った仮のプールで、コードの通り道だけを確かめたもの'
              if spec['dry_run'] else '本番（新しい未接触データでの1回だけの評価）'),
        git=gstate, git_checked=False, python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
        dev_dir=os.path.abspath(dev_dir) if dev_dir else None, komo_dir=shown_path(komo_dir, out_dir),
        symbols=[s for s in spec['symbols'] if s in infos], missing_symbols=missing, komo=infos,
        s_nom=OrderedDict(S_NOM), digits=OrderedDict(DIGITS), extra_s_nom=OrderedDict(EXTRA_S_NOM),
        contact=contact, pools=OrderedDict(
            [('U-D', OrderedDict(symbols=list(SYMBOLS), period=list(spec['ud']), series='komo135', role='判定')),
             ('U-E', OrderedDict(symbols='対応表の銘柄', period=list(spec['ue']), series='利用者の MT5', role='判定')),
             ('U-X', OrderedDict([('symbols', list(NEW)), ('period', list(spec['ux'])), ('from', OrderedDict(spec['ux_from'])),
                                  ('series', 'komo135'), ('role', '参考')])),
             ('U-E後', OrderedDict(symbols='U-E と同じ', period=list(spec['ue_after']), series='利用者の MT5', role='参考')),
             ('データ源の照合', OrderedDict(symbols=list(USED), period=list(spec['src_check']), series='komo135',
                                      role='参考'))]),
        midpoints=pool_midpoints(spec), cut=list(spec['cut']), configs=list(CONFIGS),
        config_labels=OrderedDict((c, CONFIG_LABEL[c]) for c in CONFIGS), dry_alias=spec.get('dry_alias'),
        komo_clip=spec['komo_clip'])


# ---------------------------------------------------------------- 第1段
def run_stage1(komo_dir=None, out_dir=None, manifest=None, workers=4, dry_run=False, dev_dir=None, log=print, spec=None,
               require_clean_git=True, rerun_reason=None):
    """第1段（§7）: komo135 の12銘柄で v1.1・fusion・1.5倍を1回だけ走らせ、U-D・U-X の取引数・平均R・標準誤差、打ち切りの判定、
    データ源の照合、切断テストを出す。spec・require_clean_git の差し替えはテスト専用（CLI からは変えられない）"""
    t_start = time.perf_counter()
    spec = spec or make_spec(dry_run)
    dry = bool(spec['dry_run'])
    L = RunLog(log)
    _start(spec, dry, L, 1, out_dir)
    problems = []
    if dry:
        if komo_dir or manifest:
            raise SystemExit('[v11_eval] ドライランは開発データだけを使う（--komo-dir・--manifest は渡さない）')
        if not dev_dir:
            raise SystemExit('[v11_eval] ドライランには --dev-dir（開発データのフォルダ）が要る')
        dry_in = make_dry_inputs(dev_dir, os.path.join(out_dir, 'dry_input'), spec, stage=1, log=L)
        komo_dir, manifest, ref_path = dry_in['komo_dir'], dry_in['manifest'], dry_in['ref_trades']
    else:
        if not komo_dir:
            raise SystemExit('[v11_eval] --komo-dir が要る')
        ref_path = spec['ref_trades']
    if manifest is None and not dry:                           # 事前登録 §2 に書いた第1段の前の確認の結果を使う
        contact, cp = prereg_stage1_contact()
        contact = contact or OrderedDict(asked_on='', summary='', excluded=[], partial=[])
        contact_source = f'事前登録 {PREREG} §2'
    else:
        contact, cp = parse_contact(load_manifest(manifest), required=not dry)
        contact_source = 'ドライランの仮の記録' if dry else '記録ファイル（--manifest）'
    contact['source'] = contact_source
    problems += cp
    gstate = git_state()
    files, infos, missing = _load_komo_all(komo_dir, spec, dry, problems, L)
    if not infos:
        problems.append('komo135 のファイルが1つもない')
    if not dry and require_clean_git:
        problems += git_problems(gstate) + prereg_problems()
    ref, ref_info = None, None
    if ref_path and os.path.exists(ref_path):
        ref, ref_info = load_ref_trades(ref_path, spec['ref_config'], spec['ref_pool'])
    elif not dry:
        problems.append(f'データ源の照合に使う v1.0 の取引一覧 {ref_path} がない')
    if problems:
        raise SystemExit('[v11_eval] 実行前の確認で止めた（何も計算していない）:\n  - ' + '\n  - '.join(problems))
    L.open(os.path.join(out_dir, 'stage1_run.log'), dry, rerun_reason)
    try:
        return _stage1_body(spec, dry, komo_dir, files, infos, missing, contact, gstate, ref, ref_info, out_dir, workers,
                            L, t_start, dev_dir, require_clean_git)
    finally:
        L.close()


def _stage1_body(spec, dry, komo_dir, files, infos, missing, contact, gstate, ref, ref_info, out_dir, workers, L,
                 t_start, dev_dir, require_clean_git):
    syms = [s for s in spec['symbols'] if s in infos]
    cut_sym, cut = spec['cut']
    jobs = [('komo', s, c, None) for s in syms for c in CONFIGS]
    if cut_sym in syms:
        jobs.append(('komo', cut_sym, MAIN, cut))
    L(f'[v11_eval] 実行: komo135 {len(syms)}銘柄 × {len(CONFIGS)}構成（{"・".join(CONFIGS)}）＋切断テスト = {len(jobs)}件、'
      f'{workers}並列。素朴ベースライン・P1〜P6・PSR は第1段では計算しない（§7）')
    ctx = dict(komo=dict(files), komo_clip=spec['komo_clip'], mt5={}, mt5_clip=None, clock=None)
    with Runner(ctx, workers, L) as rn:
        out = rn.run(jobs)
        cpu = rn.cpu
    check_infos(out, infos, 'komo')
    t_run = time.perf_counter() - t_start
    T = OrderedDict((c, chrono(assign(d, spec, contact))) for c, d in gather(out, CONFIGS, ('komo',)).items())
    cut_check = None
    if (('komo', cut_sym, MAIN, None) in out) and (('komo', cut_sym, MAIN, cut) in out):
        part = out[('komo', cut_sym, MAIN, cut)]
        cut_check = truncation_check(out[('komo', cut_sym, MAIN, None)][0], part[0], cut, part[2], cut_sym)
    src = source_check(T[REF], ref, spec, syms) if ref is not None else None
    if src is not None:
        src['reference'] = ref_info
    meta = _meta_common(spec, gstate, contact, komo_dir, infos, missing, out_dir, 1, dev_dir)
    meta['git_checked'] = bool(not dry and require_clean_git)
    res = analyze_stage1(T, contact, cut_check, src, meta)
    res['trades_file'] = write_trades(os.path.join(out_dir, 'stage1_trades.csv.gz'), T, CONFIGS)
    _write_json(os.path.join(out_dir, 'stage1_results.json'), res)
    with open(os.path.join(out_dir, 'stage1_report.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_stage1(clean(res)))
    st = res['stop']
    tag = '（ドライラン・数値は無意味）' if dry else ''
    L(f"[v11_eval] 第1段の判定{tag}: {st['verdict']}（v1.1 の U-D {st['trades']}回、平均 {_n(st['avg_r'])}R、"
      f"標準誤差 {_n(st['se'], '{:.3f}')}）")
    L(f"[v11_eval] 出力: {out_dir}/stage1_results.json, stage1_report.md, stage1_trades.csv.gz"
      f"（SHA-256 {res['trades_file']['sha256']}）, stage1_run.log")
    L(f'[v11_eval] 所要時間: 実行 {t_run:.0f}秒（仕事の CPU 時間の合計 {cpu:.0f}秒）、合計 {time.perf_counter() - t_start:.0f}秒。'
      f'ピークメモリ: 本体 {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}MB、'
      f'子プロセスの最大 {resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024:.0f}MB')
    return res


def analyze_stage1(T, contact, cut_check, src, meta):
    """§7 の「第1段で出すもの」だけ（取引数・平均R・標準誤差、打ち切り、データ源の照合、切断テスト）"""
    res = OrderedDict(meta=meta)
    blocks = OrderedDict()
    for c in CONFIGS:
        d = T[c]
        ud = d[d['pool'] == 'U-D']
        ud_j = ud[ud['contact'] != 'excluded']
        ux = d[d['pool'] == 'U-X']
        chf = ux[ux['chf_excl'] == 1]
        blk = OrderedDict()
        blk['U-D'] = nse(ud_j)
        if contact['partial']:
            blk['U-D_excl_partial'] = nse(ud_j[ud_j['contact'] != 'partial'])
        if contact['excluded']:
            blk['U-D_contact_excluded'] = nse(ud[ud['contact'] == 'excluded'])
        blk['U-X'] = nse(ux[ux['chf_excl'] == 0])
        blk['U-X_incl'] = nse(ux)
        blk['U-X_chf_excluded'] = nse(chf)
        blk['U-X_chf_excluded']['trades_list'] = [
            OrderedDict(symbol=r.symbol, entry_time=r.entry_time, exit_time=r.exit_time, exit_reason=r.exit_reason,
                        pnl_r=r.pnl_r) for r in chf.itertuples()]
        blocks[c] = blk
    res['configs'] = blocks
    res['stop'] = stop_rule(blocks[MAIN]['U-D'])
    res['source_check'] = src
    res['truncation'] = cut_check
    return res


# ---------------------------------------------------------------- 第2段
def load_stage1(stage1_dir, dry):
    """第1段の出力を読み、取引一覧の SHA-256 を確かめる。戻り値 (記録, 取引一覧のパス, 問題)"""
    problems = []
    p = os.path.join(stage1_dir, 'stage1_results.json')
    if not os.path.exists(p):
        return None, None, [f'第1段の結果 {p} がない（第1段と同じ --out を渡すか、--stage1-dir で第1段の出力フォルダを指す）']
    with open(p, encoding='utf-8') as f:
        js = json.load(f)
    meta = js.get('meta') or {}
    tfile = js.get('trades_file') or {}
    if meta.get('stage') != 1:
        problems.append(f'{p} は第1段の結果ではない')
    if bool(meta.get('dry_run')) != bool(dry):
        problems.append('第1段と第2段で、ドライランと本番が混ざっている')
    tf = os.path.join(stage1_dir, tfile.get('file', 'stage1_trades.csv.gz'))
    if not os.path.exists(tf):
        problems.append(f'第1段の取引一覧 {tf} がない')
    elif sha256_of(tf) != tfile.get('sha256'):
        problems.append(f'第1段の取引一覧 {tf} の SHA-256 が、第1段の結果に書いた値と違う')
    if (js.get('stop') or {}).get('stop') and not dry:
        problems.append('第1段で打ち切り（不合格）になっている。第2段は行わない（§7）')
    return js, tf, problems


def stage1_link(st1, contact, gstate, code_fix_reason):
    """第1段との約束（§2・§7.2）: 第1段の接触の申告が第2段の記録で覆われているか、評価に使うファイルが第1段のコミットから
    変わったか。戻り値 (記録, 接触の申告の問題, コードの問題)。止めるかどうかは呼び出し側（本番だけ止める）"""
    m1 = (st1 or {}).get('meta') or {}
    c1 = (m1.get('git') or {}).get('commit')
    head = gstate.get('commit')
    missing = contact_missing(m1.get('contact') or {}, contact)
    changed = [] if c1 and c1 == head else code_changes_since(c1)
    rec = OrderedDict(stage1_commit=c1, head=head, same_commit=bool(c1 and c1 == head), eval_files_changed=changed,
                      code_fix_reason=code_fix_reason or None, stage1_asked_on=(m1.get('contact') or {}).get('asked_on'),
                      contact_missing=missing)
    cp = (['第1段の接触の申告が第2段の記録（contact）で覆われていない（第1段の記録を残して書き足す）: ' + '、'.join(missing)]
          if missing else [])
    gp = []
    if changed is None:
        gp.append('第1段のコミットとの差分が git で取れない（§7.2：第1段と同じコードで走らせる）')
    elif changed and not code_fix_reason:
        gp.append('評価に使うファイルが第1段のコミットから変わっている: ' + '、'.join(changed) + '。第1段と同じコードで走らせる'
                  '（§7.2）。結果のファイルができる前の技術的な失敗を直したときだけ、--code-fix-reason に理由を書く')
    return rec, cp, gp


def prepare_mt5(mt5_files, spec, contact, problems, log):
    """§3.2 の読み込み（実行前に行う。戦略は走らせない）: 生の時刻のまま読み、H1 か確かめ、FX の銘柄の生の時刻で時計を判定し、
    換算してから土日・重複を除いて期間で切り、エントリーを数える期間と最低限の量を求める。読めない・H1 でない・換算で例外が
    出たファイルは problems に足す（何も計算しないうちに止めるため）。戻り値 (時計の判定, 換算, 足の記録, 期間と量)"""
    raw = OrderedDict()
    for s, p in mt5_files.items():
        try:
            r = read_mt5_raw(p)
        except Exception as e:
            problems.append(f'{p}: 読み込みに失敗（{type(e).__name__}: {e}）')
            continue
        step = bar_step(r.index)
        if step != HOUR:
            problems.append(f'{p}: 足の間隔の最頻値が {step}（H1 の書き出しでない）')
            continue
        raw[s] = r
    clock = detect_clock(OrderedDict((s, r.index) for s, r in raw.items() if s in FX))     # XAUUSD にも同じ換算を使う
    log(f"[v11_eval] 時刻の判定: {clock['label']}（判定に使った銘柄×週 {clock['weeks_used']}、①{_pct(clock['frac_ny7'])}・"
        f"②{_pct(clock['frac_athens'])}・③ {clock['const_hours']}時間 {_pct(clock['frac_const'])}）")
    if clock['kind'] is None:
        return clock, None, OrderedDict(), None
    conv = {'kind': clock['kind'], 'hours': clock['hours'] or 0}
    infos = OrderedDict()
    for s, r in raw.items():
        try:
            _, info = load_mt5(mt5_files[s], s, conv, spec['mt5_clip'], raw=r)
        except Exception as e:                                 # 換算の重なり・抜け（起きないはず）など
            problems.append(f'{mt5_files[s]}: 換算に失敗（{type(e).__name__}: {e}）')
            continue
        infos[s] = info
        log(f"[v11_eval] MT5 {s}: {info['file']} {info['rows']}行 → {info['bars']}本 {info['first']}〜{info['last']}"
            f"（NY+7）SHA-256 {info['sha256'][:12]}…")
    ue = ue_windows(infos, spec, contact)
    log(f"[v11_eval] 最低限の量: 使える銘柄 {ue['symbols']}（{ue['min_symbols']}以上）、U-E {ue['symbol_years']:.1f}銘柄年"
        f"（{ue['min_symyears']:g}以上）→ {'満たす' if ue['ok'] else '満たさない'}")
    return clock, conv, infos, ue


def run_stage2(komo_dir=None, mt5_dir=None, manifest=None, out_dir=None, stage1_dir=None, workers=4, dry_run=False,
               dev_dir=None, log=print, spec=None, require_clean_git=True, naive_p=NAIVE_P, naive_seeds=NAIVE_SEEDS,
               rerun_reason=None, code_fix_reason=None, today=None):
    """第2段（§7）: komo135（U-D）と利用者の MT5（U-E）で全構成と素朴ベースラインを1回だけ走らせ、判定プール U-D＋U-E で
    P1〜P6 を判定する。第1段の出力は stage1_dir（既定は out_dir）から読む。時刻の判定ができない・最低限の量に届かないときは、
    戦略を走らせずに「未決」と書く。spec・naive_p・naive_seeds・require_clean_git・today の差し替えはテスト専用（CLI からは変えられない）"""
    t_start = time.perf_counter()
    spec = spec or make_spec(dry_run)
    dry = bool(spec['dry_run'])
    L = RunLog(log)
    _start(spec, dry, L, 2, out_dir)
    problems = []
    st1_given = stage1_dir is not None
    stage1_dir = stage1_dir if st1_given else out_dir
    if dry:
        if komo_dir or mt5_dir or manifest:
            raise SystemExit('[v11_eval] ドライランは開発データだけを使う（--komo-dir・--mt5-dir・--manifest は渡さない）')
        if not dev_dir:
            raise SystemExit('[v11_eval] ドライランには --dev-dir（開発データのフォルダ）が要る')
        dry_in = make_dry_inputs(dev_dir, os.path.join(out_dir, 'dry_input'), spec, stage=2, log=L)
        komo_dir, mt5_dir, manifest = dry_in['komo_dir'], dry_in['mt5_dir'], dry_in['manifest']
        ref_path = dry_in['ref_trades']
    else:
        if not (komo_dir and mt5_dir and manifest):
            raise SystemExit('[v11_eval] --komo-dir・--mt5-dir・--manifest が要る')
        ref_path = spec['ref_trades']
    man = load_manifest(manifest)
    contact, cp = parse_contact(man, required=not dry)
    contact['source'] = 'ドライランの仮の記録' if dry else '記録ファイル（--manifest）'
    broker, smap, mp_ = parse_stage2_manifest(man, required=not dry)
    problems += cp + mp_
    gstate = git_state()
    st1, st1_trades, link = None, None, None
    if not dry or st1_given or os.path.exists(os.path.join(stage1_dir, 'stage1_results.json')):
        st1, st1_trades, sp = load_stage1(stage1_dir, dry)       # ドライランは第1段がなくても通す（照合を省く）
        problems += sp
    if st1 is not None:
        link, link_cp, link_gp = stage1_link(st1, contact, gstate, code_fix_reason)
        if not dry:
            problems += link_cp + (link_gp if require_clean_git else [])
    files, infos, missing = _load_komo_all(komo_dir, spec, dry, problems, L)
    if not infos:
        problems.append('komo135 のファイルが1つもない')
    if st1 is not None:
        for s, info in infos.items():
            want = ((st1.get('meta') or {}).get('komo') or {}).get(s, {}).get('sha256')
            if want != info['sha256']:
                problems.append(f'komo135 の {s} のファイルが第1段と違う（SHA-256）')
    mt5_files = OrderedDict()
    for s in spec['symbols']:
        if smap[s]['broker_symbol'] is None:
            continue
        p = os.path.join(mt5_dir, f'{s}_H1.csv')
        if os.path.isfile(p):
            mt5_files[s] = p
        else:
            problems.append(f'対応表にある {s}（{smap[s]["broker_symbol"]}）のファイル {p} がない')
    run_date = None
    if not dry:
        run_date = str(pd.Timestamp(today if today is not None else pd.Timestamp.now()).date())
        problems += deadline_problems(today)
        if require_clean_git:
            problems += git_problems(gstate) + prereg_problems()
    ref, ref_info = None, None
    if ref_path and os.path.exists(ref_path):
        ref, ref_info = load_ref_trades(ref_path, spec['ref_config'], spec['ref_pool'])
    elif not dry:
        problems.append(f'データ源の照合に使う v1.0 の取引一覧 {ref_path} がない')
    clock, conv, mt5_infos, ue = prepare_mt5(mt5_files, spec, contact, problems, L)
    if problems:
        raise SystemExit('[v11_eval] 実行前の確認で止めた（何も計算していない）:\n  - ' + '\n  - '.join(problems))
    L.open(os.path.join(out_dir, 'stage2_run.log'), dry, rerun_reason)
    try:
        return _stage2_body(spec, dry, komo_dir, mt5_dir, files, infos, missing, mt5_files, clock, conv, mt5_infos, ue,
                            contact, broker, smap, gstate, st1, st1_trades, stage1_dir, link, ref, ref_info, out_dir,
                            workers, L, t_start, dev_dir, require_clean_git, list(naive_p), list(naive_seeds), run_date)
    finally:
        L.close()


NAIVE_KEPT = ('素朴ベースラインの取引一覧は、komo135 の系列は U-D の開始以降、利用者の系列は U-E の開始以降にエントリーした'
              '取引だけ（P4 と p の選び方は判定プールだけを使う。系列は先頭から走らせる）')


def _stage2_body(spec, dry, komo_dir, mt5_dir, files, infos, missing, mt5_files, clock, conv, mt5_infos, ue, contact,
                 broker, smap, gstate, st1, st1_trades, stage1_dir, link, ref, ref_info, out_dir, workers, L, t_start,
                 dev_dir, require_clean_git, naive_p, naive_seeds, run_date):
    meta = _meta_common(spec, gstate, contact, komo_dir, infos, missing, out_dir, 2, dev_dir)
    meta['git_checked'] = bool(not dry and require_clean_git)
    meta.update(mt5_dir=shown_path(mt5_dir, out_dir), broker=broker, symbol_map=smap,
                stage1_dir=shown_path(stage1_dir, out_dir) if st1 is not None else None,
                naive_grid=naive_p, naive_seeds=naive_seeds,
                prereg_naive=(naive_p == NAIVE_P and naive_seeds == NAIVE_SEEDS), naive_kept=NAIVE_KEPT,
                seeds=OrderedDict(month_block=12345, reps=10000,
                                  naive='numpy.random.default_rng(seed*1000+番号)。komo135 は 0〜11、利用者の系列は 100〜111'),
                run_date=run_date, deadline=str(STAGE2_DEADLINE.date()), clock=clock, mt5=mt5_infos, ue_windows=ue,
                stage1_link=link)
    if st1 is not None:
        m1 = st1.get('meta') or {}
        meta['stage1'] = OrderedDict(commit=(m1.get('git') or {}).get('commit'),
                                     same_commit=bool(link and link['same_commit']),
                                     verdict=(st1.get('stop') or {}).get('verdict'), trades_file=st1.get('trades_file'),
                                     truncation=st1.get('truncation'), contact=m1.get('contact'))
    if clock['kind'] is None:
        return _undecided(meta, out_dir, L, f"時刻の判定ができない（{clock.get('reason', '')}）。U-E は未決（§3.2）")
    if not ue['ok']:
        if not dry:
            return _undecided(meta, out_dir, L, '最低限の量（使える銘柄8以上、U-E 30銘柄年以上）に届かない。'
                                                '第2段は行わず未決（§3.2）')
        L('[v11_eval] 最低限の量に届かないが、ドライランなので続ける')
    usable = ue['usable']
    ctx = dict(komo=dict(files), komo_clip=spec['komo_clip'], mt5=OrderedDict((s, mt5_files[s]) for s in usable),
               mt5_clip=spec['mt5_clip'], clock=conv,
               naive_from=OrderedDict(komo=day_range(*spec['ud'])[0], mt5=day_range(*spec['ue'])[0]))
    syms = [s for s in spec['symbols'] if s in infos]
    naive_cfgs = [naive_name(p, s) for p in naive_p for s in naive_seeds]
    jobs_a = [('komo', s, c, None) for s in syms for c in CONFIGS]
    jobs_b = ([('komo', s, c, None) for c in naive_cfgs for s in syms]           # 重い（長い系列の）仕事から先に
              + [('mt5', s, c, None) for s in usable for c in CONFIGS]
              + [('mt5', s, c, None) for c in naive_cfgs for s in usable])
    L(f'[v11_eval] 実行: komo135 {len(syms)}銘柄・利用者 {len(usable)}銘柄 × 構成3つ＋素朴ベースライン'
      f'（{len(naive_p)}×{len(naive_seeds)}）= {len(jobs_a) + len(jobs_b)}件、{workers}並列')
    with Runner(ctx, workers, L) as rn:
        out = rn.run(jobs_a, 'A')
        check_infos(out, infos, 'komo')
        consistency = None
        if st1_trades is not None:
            consistency = compare_with_stage1(st1_trades, gather(out, CONFIGS, ('komo',)), spec)
            L('[v11_eval] 第1段の取引一覧との照合: U-D の v1.1 の取引 '
              + ('全件一致' if consistency['gate_ok'] else '**一致しない**') + '、komo135 の3構成の全取引 '
              + ('全件一致' if consistency['all_match'] else '一致しない（逸脱として記録する）'))
            if not consistency['gate_ok'] and not dry:
                _write_json(os.path.join(out_dir, 'stage2_stage1_mismatch.json'), consistency)
                raise SystemExit('[v11_eval] 走らせ直した U-D の v1.1 の取引が第1段の取引一覧と一致しない（§7.2）。'
                                 '判定はしない（stage2_stage1_mismatch.json に最初の食い違い）')
        out.update(rn.run(jobs_b, 'B'))
        cpu = rn.cpu
    check_infos(out, mt5_infos, 'mt5')
    t_run = time.perf_counter() - t_start
    L('[v11_eval] 集計中…')
    meta['stage1_consistency'] = consistency
    T = OrderedDict((c, chrono(assign(d, spec, contact, ue['start']))) for c, d in gather(out, CONFIGS).items())
    N = OrderedDict((c, chrono(assign(d, spec, contact, ue['start']))) for c, d in gather(out, naive_cfgs).items())
    del out
    src = source_check(T[REF], ref, spec, syms) if ref is not None else None
    if src is not None:
        src['reference'] = ref_info
    res = analyze_stage2(T, N, spec, ue, contact, naive_p, naive_seeds, src, meta)
    res['trades_file'] = write_trades(os.path.join(out_dir, 'stage2_trades.csv.gz'), T, CONFIGS)
    res['naive_trades_file'] = write_trades(os.path.join(out_dir, 'stage2_naive_trades.csv.gz'), N, naive_cfgs)
    _write_json(os.path.join(out_dir, 'stage2_results.json'), res)
    with open(os.path.join(out_dir, 'stage2_report.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_stage2(clean(res)))
    v = res['verdict']
    tag = '（ドライラン・数値は無意味）' if dry else ''
    L(f"[v11_eval] 判定{tag}: {v['label']}  " + ' '.join(f'{k}={OK[v[k]["ok"]]}' for k in PS))
    L(f'[v11_eval] 出力: {out_dir}/stage2_results.json, stage2_report.md, stage2_trades.csv.gz, '
      f'stage2_naive_trades.csv.gz, stage2_run.log')
    L(f'[v11_eval] 所要時間: 実行 {t_run:.0f}秒（仕事の CPU 時間の合計 {cpu:.0f}秒）、合計 {time.perf_counter() - t_start:.0f}秒。'
      f'ピークメモリ: 本体 {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f}MB、'
      f'子プロセスの最大 {resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024:.0f}MB')
    return res


def _undecided(meta, out_dir, L, reason):
    """§3.2: 時刻の判定ができない・最低限の量に届かない → 何も走らせずに「未決」と書く"""
    res = OrderedDict(meta=meta, verdict=OrderedDict(label='未決', status='undecided', reason=reason, **{'pass': False}))
    _write_json(os.path.join(out_dir, 'stage2_results.json'), res)
    with open(os.path.join(out_dir, 'stage2_report.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_undecided(clean(res)))
    L(f'[v11_eval] 判定: 未決（{reason}）。戦略は走らせていない')
    return res


def ux_block(d):
    ux = d[d['pool'] == 'U-X']
    return OrderedDict(excl=fe.summary(ux[ux['chf_excl'] == 0]), incl=fe.summary(ux),
                       chf_excluded=fe.summary(ux[ux['chf_excl'] == 1]))


def stage2_block(d, syms, contact):
    """1構成の成績（判定プール・プール別・前半後半・内訳・参考）。d は assign 済み・時刻順"""
    J = judge_frame(d)
    blk = OrderedDict()
    blk['judge'] = fe.summary(J, boot=True)
    blk['pools'] = OrderedDict((p, fe.summary(J[J['pool'] == p], boot=True)) for p in JUDGE_POOLS)
    blk['halves'] = OrderedDict((h, fe.summary(J[J['half'] == h])) for h in HALVES)
    blk['pool_halves'] = OrderedDict((f'{p} {h}', fe.summary(J[(J['pool'] == p) & (J['half'] == h)]))
                                     for p in JUDGE_POOLS for h in HALVES)
    blk['by_symbol'] = by(J, 'symbol', [s for s in syms if (J['symbol'] == s).any()])
    blk['by_pool_symbol'] = OrderedDict((p, by(J[J['pool'] == p], 'symbol', [s for s in syms if (
        (J['pool'] == p) & (J['symbol'] == s)).any()])) for p in JUDGE_POOLS)
    blk['long_short'] = OrderedDict((lab, fe.summary(J[J['direction'] == v])) for lab, v in (('買い', 1), ('売り', -1)))
    blk['by_year'] = by(J, 'year')
    blk['by_reason'] = by(J, 'exit_reason')
    blk['top1'] = fe.judge_p5(J['pnl_r'].to_numpy(dtype=float))
    blk['gap'] = gap_block(J, syms)
    blk['ue_after'] = fe.summary(J[J['ue_after'] == 1], boot=True)
    blk['ux'] = ux_block(d)
    if contact['partial']:
        Jp = J[J['contact'] != 'partial']
        blk['excl_partial'] = OrderedDict(judge=fe.summary(Jp, boot=True), pools=OrderedDict(
            (p, fe.summary(Jp[Jp['pool'] == p])) for p in JUDGE_POOLS), partial_trades=int((J['contact'] == 'partial').sum()),
            top1=fe.judge_p5(Jp['pnl_r'].to_numpy(dtype=float)))
    if contact['excluded']:
        blk['contact_excluded'] = OrderedDict(
            (p, fe.summary(d[(d['pool'] == p) & (d['contact'] == 'excluded')])) for p in JUDGE_POOLS)
    return blk


def naive_block(N, target, naive_p, naive_seeds):
    """§6: p は回数だけで選ぶ（判定プールの取引数）。選んだ p の20シードの判定プールの平均R を P4 に使う"""
    if not (naive_p and naive_seeds and all(naive_name(p, s) in N for p in naive_p for s in naive_seeds)):
        return OrderedDict(available=False, grid=naive_p, seeds=naive_seeds, chosen_seed_avg_r=[])
    counts = OrderedDict((p, [int(len(judge_frame(N[naive_name(p, s)]))) for s in naive_seeds]) for p in naive_p)
    mean_counts = OrderedDict((p, float(np.mean(v))) for p, v in counts.items())
    sel = choose_naive_p(mean_counts, target)
    seeds = OrderedDict((s, fe.summary(judge_frame(N[naive_name(sel['p'], s)]))) for s in naive_seeds)
    return OrderedDict(available=True, grid=naive_p, seeds=naive_seeds, counts=counts, mean_counts=mean_counts,
                       selection=sel, chosen_seed_summaries=seeds,
                       chosen_seed_avg_r=[seeds[s]['avg_r'] for s in naive_seeds])


PS = ['P1', 'P2', 'P3', 'P4', 'P5', 'P6']


def analyze_stage2(T, N, spec, ue, contact, naive_p, naive_seeds, src, meta):
    """§8・§9 の全項目（判定プール U-D＋U-E）"""
    res = OrderedDict(meta=meta)
    syms = [s for s in SYMBOLS if any((T[c]['symbol'] == s).any() for c in T)]
    blocks = OrderedDict((c, stage2_block(T[c], syms, contact)) for c in CONFIGS if c in T)
    res['configs'] = blocks
    f = blocks[MAIN]
    J = judge_frame(T[MAIN])
    res['naive'] = naive_block(N, f['judge']['trades'], naive_p, naive_seeds)
    res['psr'] = psr_block(J, spec['psr_months'])
    sym_stats = OrderedDict((s, (v['trades'], v['avg_r'])) for s, v in f['by_symbol'].items())
    v = OrderedDict()
    v['P1'] = fe.judge_p1(f['judge'])
    v['P2'] = judge_p2(OrderedDict((p, f['pools'][p]['avg_r']) for p in JUDGE_POOLS), sym_stats)
    v['P3'] = fe.judge_p3(f['halves']['前半']['avg_r'], f['halves']['後半']['avg_r'])
    v['P4'] = judge_p4(f['judge']['avg_r'], res['naive']['chosen_seed_avg_r'])
    v['P5'] = f['top1']
    v['P6'] = OrderedDict(ok=res['psr']['ok'], psr=res['psr']['psr'], threshold=P6_MIN)
    v['pass'] = all(v[k]['ok'] for k in PS)
    v['label'] = '合格' if v['pass'] else '不合格'
    span_lo, span_hi = day_range(*spec['ud'])[0], day_range(*spec['ue'])[1]
    years = (span_hi - span_lo) / YEAR
    eu_segs = [day_range(*spec['ud'])]
    if 'EURUSD' in ue['start']:
        eu_segs.append((pd.Timestamp(ue['start']['EURUSD']), day_range(*spec['ue'])[1]))
    eu10 = ten_month(J[J['symbol'] == 'EURUSD'], eu_segs)
    v['warnings'] = OrderedDict(
        long_short=warn_long_short(f['long_short']['買い']['avg_r'], f['long_short']['売り']['avg_r']),
        gap_fallback=warn_gap(f['gap']['fx'], years),
        eurusd_10m=warn_ten_month(eu10['mean']))
    v['eurusd_10m'] = eu10
    res['verdict'] = v
    res['diff_v11_fusion'] = OrderedDict(
        [('judge', delta(f['judge'], blocks[REF]['judge']))]
        + [(p, delta(f['pools'][p], blocks[REF]['pools'][p])) for p in JUDGE_POOLS])
    res['source_check'] = src
    return res


# ---------------------------------------------------------------- 報告書
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


OK = {True: '○', False: '×'}


def _nse_cell(x):
    if not x:
        return '—'
    return f"{x['trades']}回 / " + (f"{_n(x['avg_r'])}R" if finite(x['avg_r']) else '—') + f" / {_n(x['se'], '{:.3f}')}"


def _dry_banner(m):
    if not m['dry_run']:
        return []
    return ['> **ドライラン：数値は無意味**。開発データ（2013〜2017）の中に作った仮のプールで、評価スクリプトの通り道だけを'
            '確かめたものです。新しい5銘柄は開発データの別の銘柄に名前を付け替えたもの'
            '（' + '、'.join(f'{s}←{a}' for s, a in (m.get('dry_alias') or {}).items() if s != a) + '）、'
            '接触の申告・ブローカー・対応表は仮のものです。数値は優位性について何も言いません。', '']


def _git_lines(m):
    g = m['git']
    dirty = g.get('eval_files_dirty') or []
    L = [f"- 実行したコミット：`{g.get('commit')}`（事前登録を最後に変えたコミット：`{g.get('prereg_commit')}`）"]
    if m.get('git_checked'):
        L.append('- 評価に使うファイル（' + '、'.join(f'`{x}`' for x in g['eval_files']) + '）がコミット済みであること、'
                 '事前登録に「' + FROZEN_MARK + '」の注記がない（凍結した）ことを確かめてから実行した')
    else:
        L.append('- git の確認：' + ('ドライランなので省いた' if m['dry_run'] else '**省いた（テスト用の設定）**')
                 + ('。未コミットの変更：' + '、'.join(dirty) if dirty else '')
                 + ('。git に登録されていない：' + '、'.join(g.get('eval_files_untracked') or [])
                    if g.get('eval_files_untracked') else ''))
    return L


def _contact_lines(c):
    src = f"（{c['source']}）" if c.get('source') else ''
    L = [f"- §2 の利用者への確認{src}：{c.get('asked_on') or '（記録なし）'}。{c.get('summary') or ''}"]
    for key, lab in (('excluded', '判定から除いた銘柄×期間（fusion 系を見た）'), ('partial', '「一部汚れ」（旧 EA・覚えていない）')):
        items = c.get(key) or []
        L.append(f'- {lab}：' + ('、'.join(f"{e['symbol']} {e['from']}〜{e['to']}（{e['reason']}）" for e in items)
                                 if items else 'なし'))
    return L


def _komo_table(infos):
    return _table(['銘柄', 'ファイル', 'SHA-256', '行数', '生の期間（Europe/Athens）', '換算後の期間（NY+7）', '使った足',
                   '土日で除いた足', '重複', '整数倍の確認', '端数のある値', '四本値の矛盾'],
                  [[s, i.get('path') or i['file'], f"`{i['sha256']}`", i['rows'], f"{_ts(i['raw_first'])} 〜 {_ts(i['raw_last'])}",
                    f"{_ts(i['server_first'])} 〜 {_ts(i['server_last'])}", i['bars'], i['weekend_dropped'], i['duplicates'],
                    OK[bool(i['int_check'])], i['raw_fraction_values'], i['ohlc_inconsistent']] for s, i in infos.items()])


def _source_lines(src):
    if not src:
        return ['- 照合しなかった（v1.0 の取引一覧がない）', '']
    ref = src.get('reference') or {}
    L = [f"期間 {src['window'][0]}〜{src['window'][1]}（エントリー時刻）、銘柄 {'・'.join(src['symbols'])}。"
         f"v1.0 の取引は `{ref.get('file')}` の config={ref.get('config')}・pool={ref.get('pool')}"
         f"（SHA-256 `{ref.get('sha256')}`）。この期間の成績は v1.0 で公開済みで、新しい成績の情報は含まない。", '',
         _table(['', 'komo135 版', 'v1.0（OANDA 版）'],
                [['件数', src['komo'], src['oanda']], ['平均R', _n(src['avg_r_komo']), _n(src['avg_r_oanda'])]]), '',
         f"- エントリー（銘柄・方向・時刻）が一致した件数 {src['matched']}：一致率 {_pct(src['rate'])}（÷多い方の件数）、"
         f"OANDA 版の {_pct(src['rate_vs_oanda'])}、komo135 版の {_pct(src['rate_vs_komo'])}。"
         f"参考：時刻の差 ±1時間までを一致とみなすと {src['near_matched']}件（{_pct(src['near_rate'])}）", '',
         _table(['銘柄', 'komo135', 'OANDA', '一致', '一致率', '平均R（komo135）', '平均R（OANDA）'],
                [[s, x['komo'], x['oanda'], x['matched'], _pct(x['rate']), _n(x['avg_r_komo']), _n(x['avg_r_oanda'])]
                 for s, x in src['by_symbol'].items()]), '']
    return L


def _trunc_lines(tr):
    if not tr:
        return ['- 実施していない（EURUSD がない）', '']
    return [f"- {tr['symbol']} を {_ts(tr['cut'])} で切った系列（最後の足 {_ts(tr['last_bar'])}）と全期間の系列で、"
            f"{_ts(tr['cut'])} より前に決済した v1.1 の取引 {tr['compared']}件が"
            + ('**全件一致**' if tr['match'] else '**一致しない**') + '。', '']


def render_stage1(r):
    m, st = r['meta'], r['stop']
    L = [('# 【ドライラン：数値は無意味】' if m['dry_run'] else '# ') + 'FUSION-CORE v1.1 第1段 報告書（下書き）', '']
    L += _dry_banner(m)
    L += ['## 結論（打ち切りの判定。§7）', '',
          f"- **v1.1 の U-D：{st['trades']}回、平均 {_n(st['avg_r'])}R（標準誤差 {_n(st['se'], '{:.3f}')}）→ {st['verdict']}**",
          '- 規則：v1.1 の U-D（判定に使う値。接触の申告で除いた取引を除く）の平均R ≤ 0 なら「不合格（第1段で打ち切り）」で、第2段は行わない。'
          '＞0 なら、利用者に第2段のデータ（MT5 の 2021-12 以降）を依頼する。',
          '- 第1段の値は途中経過であり、優位性の証拠としては使わない。第1段でできるのは「不合格で打ち切る」ことだけ。',
          '- P1〜P6・素朴ベースライン・PSR は第1段では計算していない（§7）。'] + _git_lines(m) + ['']
    L += ['## 1. 構成ごとの U-D と U-X（取引数・平均R・標準誤差だけ）', '',
          '各セルは「取引数 / 平均R / 標準誤差」。U-X は合否にも打ち切りにも使わない参考値。', '']
    rows = []
    for c, b in r['configs'].items():
        rows.append([m['config_labels'][c], _nse_cell(b['U-D']), _nse_cell(b['U-X']), _nse_cell(b['U-X_incl']),
                     _nse_cell(b['U-X_chf_excluded'])])
    L += [_table(['構成', 'U-D（判定）', 'U-X（2015-01-15 を含む CHF の取引を除く）', 'U-X（含める）', '除いた CHF の取引'], rows), '']
    c0 = r['configs'][MAIN]
    if 'U-D_excl_partial' in c0 or 'U-D_contact_excluded' in c0:
        L += ['### 接触の申告を当てはめた値（§2）', '',
              _table(['構成', 'U-D から「一部汚れ」も除いた値', '判定から除いた取引（接触の申告）'],
                     [[m['config_labels'][c], _nse_cell(b.get('U-D_excl_partial')), _nse_cell(b.get('U-D_contact_excluded'))]
                      for c, b in r['configs'].items()]), '']
    L += _contact_lines(m['contact']) + ['']
    chf = c0['U-X_chf_excluded']
    L += ['### U-X から除いた CHF の取引（v1.1。§4）', '',
          '- 規則：USDCHF・EURCHF で entry_time < 2015-01-16 00:00、かつ決済の足（WEEKEND・END は exit_time − 1時間）≥ 2015-01-15 00:00。', '']
    if chf['trades_list']:
        L += [_table(['銘柄', 'エントリー', '決済', '決済理由', 'R'],
                     [[x['symbol'], _ts(x['entry_time']), _ts(x['exit_time']), x['exit_reason'], _n(x['pnl_r'])]
                      for x in chf['trades_list']]), '']
    else:
        L += ['- なし', '']
    L += ['## 2. データ源の照合（§9。fusion）', ''] + _source_lines(r.get('source_check'))
    L += ['## 3. 切断テスト（§4）', ''] + _trunc_lines(r.get('truncation'))
    L += ['## 4. データの記録（§3.1）', '',
          f"- komo135 のフォルダ：`{m['komo_dir']}`" + (f"（読み込んだ足を {m['komo_clip'][0]}〜{m['komo_clip'][1]} に切った）"
                                                  if m.get('komo_clip') else ''),
          '- 変換：価格＝round(生の値)÷10^桁（円のペア3、XAUUSD 2、ほか5）→ 時刻を Europe/Athens として UTC に戻し NY+7 に換算 → '
          '換算後の時刻で土日を除き、同じ時刻は最初の足 → 四本値に s_nom/2（Bid → 仲値）。', '',
          _komo_table(m['komo']), '']
    if m['missing_symbols']:
        L += [f"- ファイルがなかった銘柄：{'、'.join(m['missing_symbols'])}", '']
    tf = r['trades_file']
    L += [f"- 取引一覧：`{tf['file']}`（{tf['rows']}行、SHA-256 `{tf['sha256']}`）。第2段で走らせ直した取引と全件一致することを確かめる。", '']
    L += ['## 5. 実行条件', '',
          f"- Python {m['python']}、numpy {m['numpy']}、pandas {m['pandas']}",
          '- 構成：' + '、'.join(m['config_labels'].values()) + '。1.5倍は戦略が使う s_nom（約定、SL バッファの下限 3×s_nom、'
          'トレールのバッファ）だけを1.5倍にし、仲値にそろえる s_nom/2 は1.5倍にしない。',
          '- s_nom：' + '、'.join(f'{s} {v:g}' for s, v in m['s_nom'].items()) + '（EURGBP・USDCHF・EURCHF は §3.1 で固定した値）',
          '- プール：' + '、'.join(f"{p} {x['period'][0]}〜{x['period'][1]}（{x['role']}）" for p, x in m['pools'].items()),
          '- 各銘柄の全期間を1本の系列として、構成ごとに1回だけ走らせ、取引をエントリー時刻（換算後の NY+7）でプールに振り分けた。', '']
    return '\n'.join(L)


def _srow(name, s, ci=False):
    row = [name, s['trades'], _pct(s['win_rate']), _n(s['total_r'], '{:+.1f}'), _n(s['avg_r'])]
    if ci:
        row.append(_ci(s.get('ci95_lo'), s.get('ci95_hi')))
    return row + [_n(s['t_stat'], '{:+.2f}'), _pf(s['pf']), _n(s['max_dd_r'], '{:+.1f}'), s['max_losing_streak'],
                  f"{s['long']}/{s['short']}"]


def _sheads(ci=False):
    return ['', '回数', '勝率', '総R', '平均R'] + (['95%区間（月ブロック）'] if ci else []) + ['t', 'PF', '最大DD(R)', '最大連敗',
                                                                                     '買い/売り']


SHORT_HEADS = ['', '回数', '勝率', '総R', '平均R', 't', 'PF']


def _short_rows(blk):
    return [[k, v['trades'], _pct(v['win_rate']), _n(v['total_r'], '{:+.1f}'), _n(v['avg_r']), _n(v['t_stat'], '{:+.2f}'),
             _pf(v['pf'])] for k, v in blk.items()]


def _mt5_lines(m):
    ck, ue = m.get('clock') or {}, m.get('ue_windows')
    L = [f"- ブローカー：{m['broker']['name']}、サーバー：{m['broker']['server']}、口座：{m['broker']['account_type']}、"
         f"書き出した日：{m['broker']['exported_on']}",
         '- 銘柄の対応表：' + '、'.join(f"{s}={x['broker_symbol']}" if x['broker_symbol'] else f"{s}=なし（{x['reason']}）"
                                    for s, x in m['symbol_map'].items()),
         f"- 時刻の判定：**{ck.get('label')}**。FX の銘柄×週 {ck.get('weeks_used')}（12/24〜1/3 を含む週と100本未満の週を除く）で、"
         f"①NY+7 {_pct(ck.get('frac_ny7'))}、②Europe/Athens {_pct(ck.get('frac_athens'))}、"
         f"③一定 {ck.get('const_hours')}時間 {_pct(ck.get('frac_const'))}（95%以上で採る。①と②の両方なら①）",
         '- o_w の分布：' + '、'.join(f'{k}時間 {v}週' for k, v in (ck.get('o_w_counts') or {}).items())]
    if m.get('mt5'):
        L += ['', _table(['銘柄', 'ファイル', 'SHA-256', '行数', '生の期間', '使った足（NY+7）', '本数', '土日で除いた足', '重複', '四本値の矛盾'],
                         [[s, i['file'], f"`{i['sha256']}`", i['rows'], f"{_ts(i['raw_first'])} 〜 {_ts(i['raw_last'])}",
                           f"{_ts(i['first'])} 〜 {_ts(i['last'])}", i['bars'], i['weekend_dropped'], i['duplicates'],
                           i['ohlc_inconsistent']] for s, i in m['mt5'].items()]), '']
    if ue:
        L += [_table(['銘柄', '使う', 'エントリーを数える期間', '接触の申告で除いた日数', '銘柄年', '理由'],
                     [[s, OK[bool(x['usable'])], f"{_ts(x.get('start'))} 〜 {_ts(x.get('end'))}" if x.get('start') else '—',
                       _n(x.get('excluded_days'), '{:.1f}'), _n(x.get('symbol_years'), '{:.2f}'), x.get('reason', '')]
                      for s, x in ue['rows'].items()]), '',
              f"- 最低限の量：使える銘柄 {ue['symbols']}（{ue['min_symbols']}以上）、U-E {ue['symbol_years']:.2f}銘柄年"
              f"（{ue['min_symyears']:g}以上）→ {'満たす' if ue['ok'] else '満たさない'}", '']
    return L


def _stage1_lines(m):
    """第1段との約束（§2・§7.2）: 判定・コード・接触の申告・取引一覧の照合"""
    s1, k, sc = m.get('stage1'), m.get('stage1_link') or {}, m.get('stage1_consistency')
    if not s1:
        return ['- 第1段の出力と照合していない（第1段の出力がない。ドライランだけ許す）']
    ch = k.get('eval_files_changed')
    if k.get('same_commit'):
        code = '同じコミット'
    elif ch == []:
        code = '評価に使うファイルは第1段のコミットから変わっていない'
    elif ch:
        code = ('**評価に使うファイルが第1段から変わった：' + '、'.join(ch) + f"。理由：{k.get('code_fix_reason') or '（なし）'}"
                '（§7.2 の技術的な修正。逸脱として記録する）**')
    else:
        code = '**第1段のコミットとの差分を git で確かめられなかった**'
    L = [f"- 第1段：{s1.get('verdict')}。第1段のコミット `{s1.get('commit')}`（{code}）"]
    miss = k.get('contact_missing') or []
    L.append('- 接触の申告：第1段の記録（確かめた日：' + (k.get('stage1_asked_on') or '—') + '）は第2段の記録に'
             + ('すべて含まれている' if not miss else '**含まれていないものがある：' + '、'.join(miss) + '**'))
    if sc:
        bad = [c for c, x in sc['configs'].items() if not x['match']]
        L.append(f"- 走らせ直した komo135 の取引と第1段の取引一覧：U-D の v1.1 の取引 {sc['gate']['stage2']}件が"
                 + ('全件一致（§7.2 の関門）' if sc['gate_ok'] else '**一致しない**')
                 + '、3構成の全取引は' + ('全件一致' if not bad else '**一致しない構成がある：' + '、'.join(bad)
                                         + '（逸脱として記録する）**'))
    return L


def render_undecided(r):
    m, v = r['meta'], r['verdict']
    L = [('# 【ドライラン：数値は無意味】' if m['dry_run'] else '# ') + 'FUSION-CORE v1.1 第2段 報告書（下書き）', '']
    L += _dry_banner(m)
    L += ['## 結論', '', f"- **判定：未決**（{v['reason']}）", '- 戦略は走らせていない。「未決」は「検証していない」という意味で、'
          '優位性があるという意味ではない（§7）。'] + _git_lines(m) + _stage1_lines(m)
    L += ['', '## 利用者のデータ（§3.2）', ''] + _mt5_lines(m)
    L += _contact_lines(m['contact'])
    return '\n'.join(L) + '\n'


def render_stage2(r):
    m, v, cf = r['meta'], r['verdict'], r['configs']
    f = cf[MAIN]
    L = [('# 【ドライラン：数値は無意味】' if m['dry_run'] else '# ') + 'FUSION-CORE v1.1 第2段 報告書（下書き）', '']
    L += _dry_banner(m)
    failed = [k for k in PS if not v[k]['ok']]
    w = v['warnings']
    L += ['## 結論', '',
          f"- **判定：{v['label']}**" + ('（P1〜P6 をすべて満たした）' if v['pass'] else f"（満たさなかった基準：{'、'.join(failed)}）"),
          f"- 警告：買いと売りの片方だけがマイナス＝{'あり' if w['long_short']['fire'] else 'なし'}、"
          f"GAP_FALLBACK（FX 11銘柄）が年1件超＝{'あり' if w['gap_fallback']['fire'] else 'なし'}"
          f"（{w['gap_fallback']['fx_count']}件／{_n(w['gap_fallback']['years'], '{:.2f}')}年）、"
          f"EURUSD の10か月あたり回数が15回未満＝{'あり' if w['eurusd_10m']['fire'] else 'なし'}"
          f"（{_n(w['eurusd_10m']['mean'], '{:.1f}')}回）"] + _git_lines(m) + _stage1_lines(m)
    if m.get('run_date'):
        L.append(f"- 実行した日：{m['run_date']}（第2段の期限 {m['deadline']} より前）")
    s1 = m.get('stage1')
    p1, p2, p3, p4, p5, p6 = (v[k] for k in PS)
    L += ['', _table(['#', '基準', '値', '判定'], [
        ['P1', '判定プールの平均R＞0、t≥2.0、月ブロック95%区間の下限＞0',
         f"平均 {_n(p1['avg_r'])}R、t={_n(p1['t'], '{:+.2f}')}、区間 {_ci(*p1['ci95'])}", OK[p1['ok']]],
        ['P2', 'U-D と U-E の両方で平均R＞0、かつ30回以上の銘柄の60%以上で平均R＞0',
         f"U-D {_n(p2['pool_avg'].get('U-D'))}R・U-E {_n(p2['pool_avg'].get('U-E'))}R、銘柄 "
         f"{len(p2['positive_symbols'])}/{len(p2['eligible_symbols'])}（{_pct(p2['frac'])}）", OK[p2['ok']]],
        ['P3', '中点（' + '、'.join(f'{k} {_ts(x)}' for k, x in m['midpoints'].items()) + '）で分けた前半どうし・後半どうしがどちらも平均R＞0',
         f"前半 {_n(p3['first_half_avg'])}R、後半 {_n(p3['second_half_avg'])}R", OK[p3['ok']]],
        ['P4', f"平均R ≥ 素朴{len(m['naive_seeds'])}シードの平均＋0.10R、かつ95パーセンタイル超",
         f"v1.1 {_n(p4['v11_avg'])}R、素朴 平均 {_n(p4['naive_mean'])}R・95%点 {_n(p4['naive_p95'])}R", OK[p4['ok']]],
        ['P5', 'R 上位1%（ceil(0.01·n) 件）を除いても平均R ≥ 0',
         f"{p5['dropped']}件を除いて {_n(p5['avg_r_after'])}R", OK[p5['ok']]],
        ['P6', 'PSR ≥ 0.95（SR₀＝0）', f"PSR={_n(p6['psr'], '{:.3f}')}", OK[p6['ok']]]]), '']
    # 1. 実行条件・データ
    L += ['## 1. 実行条件とデータ', '',
          f"- Python {m['python']}、numpy {m['numpy']}、pandas {m['pandas']}。乱数：月ブロック seed=12345・10,000回、"
          f"素朴ベースライン {m['seeds']['naive']}（seed {m['naive_seeds'][0]}〜{m['naive_seeds'][-1]}）"]
    if not m['prereg_naive']:
        L.append('- **注意：素朴ベースラインの格子・シードが事前登録と違う（テスト用の設定）**')
    L += _contact_lines(m['contact']) + ['', '### komo135（U-D・U-X）', '', _komo_table(m['komo']), '',
                                          '### 利用者の MT5（U-E。§3.2）', ''] + _mt5_lines(m)
    # 2. v1.1 の成績
    L += ['## 2. v1.1 の成績（判定プール＝U-D＋U-E。接触の申告で除いた取引を除く）', '',
          _table(_sheads(True), [_srow('判定プール', f['judge'], True)] + [_srow(p, f['pools'][p], True) for p in JUDGE_POOLS]), '',
          '### 前半・後半（P3）', '', _table(SHORT_HEADS, _short_rows(f['halves']) + _short_rows(f['pool_halves'])), '',
          '### 銘柄別（判定プール）', '', _table(SHORT_HEADS, _short_rows(f['by_symbol'])), '']
    for p in JUDGE_POOLS:
        L += [f'### 銘柄別（{p}）', '', _table(SHORT_HEADS, _short_rows(f['by_pool_symbol'][p])), '']
    L += ['### 売買別', '', _table(SHORT_HEADS, _short_rows(f['long_short'])), '',
          '### 年別（エントリーの暦年）', '', _table(SHORT_HEADS, _short_rows(f['by_year'])), '',
          '### 決済理由別', '', _table(SHORT_HEADS, _short_rows(f['by_reason'])), '',
          '### 上位1%除外（P5）', '',
          f"- 判定プール {f['top1']['n']}回のうち R の上位 {f['top1']['dropped']}件を除くと、平均 {_n(f['top1']['avg_r_after'])}R・"
          f"総 {_n(f['top1']['total_r_after'], '{:+.1f}')}R", '']
    if 'excl_partial' in f:
        ep = f['excl_partial']
        L += ['### 「一部汚れ」を除いた値（§2。判定には使わない）', '',
              f"- 判定プールのうち「一部汚れ」の取引 {ep['partial_trades']}件を除いた値。上位1%を除くと {_n(ep['top1']['avg_r_after'])}R", '',
              _table(_sheads(True), [_srow('判定プール（一部汚れを除く）', ep['judge'], True)]
                     + [_srow(p, ep['pools'][p], True) for p in JUDGE_POOLS]), '']
    if 'contact_excluded' in f:
        L += ['### 判定から除いた取引（接触の申告。別に報告する）', '',
              _table(SHORT_HEADS, _short_rows(f['contact_excluded'])), '']
    # 3. 素朴ベースライン
    nv = r['naive']
    if nv['available']:
        sel = nv['selection']
        L += ['## 3. 素朴ベースライン（§6。p は回数だけで選ぶ）', '',
              _table(['p', f"{len(nv['seeds'])}シードの判定プールの取引数の平均", 'v1.1 比'],
                     [[p, _n(c, '{:.1f}'), _n(c / sel['target'] if sel['target'] else NAN, '{:.2f}')]
                      for p, c in nv['mean_counts'].items()]), '',
              f"- v1.1 の判定プールの取引数 {sel['target']}回に最も近い p＝**{sel['p']}**（平均 {_n(sel['mean_count'], '{:.1f}')}回、"
              f"比 {_n(sel['ratio'], '{:.2f}')}）。±20% に{'入った' if sel['within_tol'] else '**入らなかった**'}。", '',
              _table(SHORT_HEADS, _short_rows(OrderedDict((f'seed {s}', x) for s, x in nv['chosen_seed_summaries'].items()))), '',
              f"- {len(nv['seeds'])}シードの平均R：平均 {_n(p4['naive_mean'])}R、95パーセンタイル {_n(p4['naive_p95'])}R"
              f"（numpy の線形補間）→ P4 は v1.1 ≥ {_n(p4.get('need'))}R かつ ＞{_n(p4['naive_p95'])}R が必要", '']
    else:
        L += ['## 3. 素朴ベースライン（§6）', '', '- 実行していない（P4 は判定できないので不合格扱い）', '']
    # 4. PSR
    d = r['psr']
    L += ['## 4. PSR（P6。§8）', '',
          _table(['項目', '値'], [
              ['系列', f"判定プールの月次R（{d['months'][0]}〜{d['months'][1]}、取引のない月は0）"], ['T（月数）', d['T']],
              ['月次Rの平均・標準偏差', f"{_n(d['mean'])}・{_n(d['sd'], '{:.3f}')}"], ['SR̂', _n(d['sr'], '{:+.4f}')],
              ['γ₃（歪度）', _n(d['skew'], '{:+.3f}')], ['γ₄（尖度）', _n(d['kurt'], '{:.3f}')], ['SR₀', '0'],
              ['PSR', _n(d['psr'], '{:.4f}')]]), '']
    # 5. 参考
    L += ['## 5. 参考（合否に使わない）', '', '### 構成の比較（判定プール）', '',
          _table(_sheads(True), [_srow(m['config_labels'][c], cf[c]['judge'], True) for c in cf]), '',
          _table(['構成'] + JUDGE_POOLS + ['U-E後'], [[m['config_labels'][c]] + [
              f"{cf[c]['pools'][p]['trades']}回 {_n(cf[c]['pools'][p]['avg_r'])}R" for p in JUDGE_POOLS]
              + [f"{cf[c]['ue_after']['trades']}回 {_n(cf[c]['ue_after']['avg_r'])}R"] for c in cf]), '']
    dd = r['diff_v11_fusion']
    L += ['- v1.1 − fusion：' + '、'.join(f"{k} {_n(x['delta'])}R（標準誤差 {_n(x['se'], '{:.3f}')}）" for k, x in dd.items()), '',
          '### U-X（新しい5銘柄 2013-03〜2020-05。準既知）', '',
          _table(SHORT_HEADS, [r_ for c in cf for r_ in _short_rows(OrderedDict(
              [(f"{c}：CHF の除外後", cf[c]['ux']['excl']), (f"{c}：含める", cf[c]['ux']['incl']),
               (f"{c}：除いた CHF の取引", cf[c]['ux']['chf_excluded'])]))]), '',
          '### U-E後（2024-09-01 以降のエントリー。規則の出どころの時期より後）', '',
          _table(_sheads(True), [_srow(m['config_labels'][c], cf[c]['ue_after'], True) for c in cf]), '']
    gp = f['gap']
    L += ['### GAP_FALLBACK（v1.1、判定プール）', '',
          f"- 合計 {gp['total']}件（FX 11銘柄 {gp['fx']}件）。FX の年あたり {_n(w['gap_fallback']['per_year'], '{:.2f}')}件",
          '- 銘柄別：' + '、'.join(f'{s} {c}' for s, c in gp['by_symbol'].items()),
          '- FX の年別：' + ('、'.join(f'{y}年 {c}' for y, c in gp['fx_by_year'].items()) or 'なし'), '',
          '### データ源の照合（§9。fusion）', ''] + _source_lines(r.get('source_check'))
    e = v['eurusd_10m']
    L += [f"- EURUSD の10か月あたり回数（判定プール、丸ごと入る暦月の連続10か月窓）：平均 {_n(e['mean'], '{:.1f}')}回"
          f"（窓 {e['windows']}個・{e['full_months']}か月）", '']
    if s1 and s1.get('truncation'):
        L += ['### 切断テスト（第1段）', ''] + _trunc_lines(s1['truncation'])
    tf, nf = r['trades_file'], r['naive_trades_file']
    L += ['## 付録：出力と定義', '',
          f"- 取引一覧：`{tf['file']}`（{tf['rows']}行、SHA-256 `{tf['sha256']}`）、素朴ベースライン `{nf['file']}`"
          f"（{nf['rows']}行、SHA-256 `{nf['sha256']}`）。" + m.get('naive_kept', ''),
          '- R は fusion/broker.py の pnl_r（スプレッド込み、初期リスク＝1R）。t＝平均÷(標準偏差÷√n)、標準偏差は ddof=1。',
          '- プールの区間は「開始日0時」以上「終了日の翌日0時」未満（エントリー時刻＝約定した足の開始時刻、換算後の NY+7）。'
          '中点ちょうどのエントリーは後半に入れる。U-E は銘柄ごとにエントリーを数え始める時刻がある（§3.2）。',
          '- 月ブロック・ブートストラップの「月」は判定プールで取引のある暦月（final_eval.month_block_ci）。',
          '- 警告の GAP_FALLBACK は FX 11銘柄（XAUUSD 以外）の判定プールの件数を、判定プールの期間の年数（365.25日）で割って判定する。', '']
    return '\n'.join(L)


# ---------------------------------------------------------------- CLI
_DOC = __doc__ or ''
MANIFEST_HELP = _DOC[_DOC.find('記録ファイル（--manifest'):_DOC.find('守ること（')] if '守ること（' in _DOC else ''


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m fusion.v11_eval',
                                 description='FUSION-CORE v1.1 の評価（fusion/PREREGISTRATION_v1_1.md。各段で1回だけ）',
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=MANIFEST_HELP)
    sub = ap.add_subparsers(dest='stage', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--komo-dir', help='komo135 の1時間足（<銘柄>h1.csv が並んだフォルダか、<銘柄>/<銘柄>h1.csv の形）')
    common.add_argument('--manifest', help='§2・§3.2 の記録（JSON。形式は下）。本番の第2段は必須。第1段は contact だけを使い、'
                                           '省くと事前登録 §2 の「第1段の前の確認の結果」を使う')
    common.add_argument('--out', required=True, help='出力フォルダ。第1段と第2段で同じフォルダを使う'
                                                     '（その段の結果のファイルがすでにあると本番は走らない）')
    common.add_argument('--workers', type=int, default=4, help='並列の数（既定4）')
    common.add_argument('--dry-run', action='store_true',
                        help='開発データの中に作った仮のプールで通り道だけを確かめる（数値は無意味）')
    common.add_argument('--dev-dir', default=os.environ.get('FUSION_DATA_DIR'),
                        help='ドライランの開発データ（<銘柄>_H1.csv。2013〜2017）。既定は環境変数 FUSION_DATA_DIR')
    common.add_argument('--rerun-reason', help='結果のファイルができる前に失敗した実行を走らせ直す理由（ログに残す。§13）')
    sub.add_parser('stage1', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=MANIFEST_HELP,
                   help='第1段: komo135 で v1.1・fusion・1.5倍を走らせ、打ち切りを判定する',
                   description='第1段（§7）: U-D・U-X の取引数・平均R・標準誤差、打ち切りの判定、データ源の照合、切断テスト')
    p2 = sub.add_parser('stage2', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
                        epilog=MANIFEST_HELP, help='第2段: 利用者の MT5 を加えて P1〜P6 を判定する',
                        description='第2段（§7）: 判定プール U-D＋U-E で P1〜P6・警告・参考項目')
    p2.add_argument('--mt5-dir', help='利用者の MT5 の書き出し（<12銘柄の名前>_H1.csv）')
    p2.add_argument('--stage1-dir', help='第1段の出力フォルダ（既定は --out。第1段と別のフォルダに出すときだけ指す）')
    p2.add_argument('--code-fix-reason', help='第1段の後に評価に使うファイルを直した理由（§7.2：結果のファイルができる前の'
                                              '技術的な失敗だけ。逸脱として記録する）')
    a = ap.parse_args(argv)
    log = lambda s: print(s, flush=True)                      # noqa: E731
    dev_dir = a.dev_dir if a.dry_run else None                # 本番では開発データを使わない
    if a.stage == 'stage1':
        return run_stage1(komo_dir=a.komo_dir, out_dir=a.out, manifest=a.manifest, workers=a.workers, dry_run=a.dry_run,
                          dev_dir=dev_dir, log=log, rerun_reason=a.rerun_reason)
    return run_stage2(komo_dir=a.komo_dir, mt5_dir=a.mt5_dir, manifest=a.manifest, out_dir=a.out, stage1_dir=a.stage1_dir,
                      workers=a.workers, dry_run=a.dry_run, dev_dir=dev_dir, log=log, rerun_reason=a.rerun_reason,
                      code_fix_reason=a.code_fix_reason)


if __name__ == '__main__':
    from fusion import v11_eval as _m                         # 子プロセスに関数を fusion.v11_eval の名前で渡すため
    _m.main()
