"""
MT5 EA（mt5/FX_Fusion_EA.mq5）のログと Python 参照実装（fusion/strategy.py）の照合ハーネス（SPEC §18）

  python -m fusion.mt5_parity --bars EURUSD_bars.csv --trades EURUSD_trades.csv \\
         [--eval EURUSD_eval.csv] --symbol EURUSD [--offset 0] [--from 2023-01-01]

入力（EA は MQL5/Files/FusionEA/ に書く。InpLogsCommon=true なら Terminal/Common/Files/FusionEA/）
  --bars    MT5 で書き出した H1 足。EA の <銘柄>_bars.csv（判定に使った足）を推奨。
            MT5 の「チャートバー」書き出しなど、fusion.data.load_mt5_csv で読める形なら何でもよい
  --trades  EA の取引ログ <銘柄>_trades.csv（仮想ブローカー）。自動売買の実約定 <銘柄>_real.csv も読める
  --eval    EA の評価ログ <銘柄>_eval.csv（任意。足ごと・方向ごとの理由コードを比べる。診断用）
  --symbol  銘柄名。EURUSD.a のような接尾辞つきでよい（先頭6文字で SPEC §10.3 の表を引く。GOLD〜 は XAUUSD）
  --offset  サーバー時間 −（NY+7）［時間］。EA の InpServerOffsetHours と同じ意味。省略時は _info.csv の値、なければ 0
  --from / --to  比べる期間（サーバー時間）。Python は足の先頭から回し、比べる範囲だけを絞る
  <銘柄>_info.csv が --trades と同じ場所にあれば自動で読み、EA と同じ条件で Python を回す:
    first_bar_time（Python をこの足から回す。足番号が EA と一致する）、switches/params（構成）、
    extra_closed/extra_early（追加の暦）、s_nom（表にない銘柄）、server_offset_h

Python 側
  fusion.strategy.run_h1 を同じ足で走らせる。サーバー時間が NY+7 でないときは、足の時刻をオフセットの分だけ戻して
  （NY+7 にそろえて）渡し、結果の時刻をサーバー時間に戻してから比べる。土日の足は、EA と同じく NY+7 に換算した
  時刻の曜日で捨てる（オフセット 0 なら fusion.data.load_mt5_csv と同じ）。
  評価ごとの理由コードは run_h1 の trace から取る。時刻・建玉による見送り（T1〜T5）と、待機注文の新規（ARMED）・
  置き直し（UPDATE）・スコア負け（LOSE）は、run_h1 と同じ順で組み立て直し、funnel の件数・取引の約定足と
  突き合わせて確かめる（合わなければ例外にする）。
  fusion/ の既存ファイルは変更しない。照合の間だけ、strategy の暦（calendar_sets）に EA と同じ追加の休場日・
  早仕舞い日を、s_nom の表に表にない銘柄の s_nom を足し、終わったら元に戻す。

比べるもの（SPEC §18）
  合格基準: 回数の差 ±5% 以内（Python 比）、エントリー時刻 ±1本で方向が一致する割合 90% 以上
            （対応がついた件数 ÷ 多い方の件数）、初期 SL の差 1ポイント以内（対応がついた全件）
  参考    : 決済理由の一致率。仮想ブローカーのログ（_trades.csv）なら「完全一致」（約定・決済の時刻と価格、
            理由、R、保有本数、key、スコア）も出す。評価ログの理由コードの一致率（診断用）
  最初の食い違いを詳しく表示し、SPEC §17 のどの分類（窓の長さ・ダウ状態機械の初期値・約定順序・スプレッド・
  欠損足・境界値の丸め・時刻ルールなど）に当たりそうかのヒントを出す。

終了コード: 0＝合格（--strict のときは完全一致も必要）、1＝不合格、2＝入力の誤り
その他    : --export-python DIR は Python の結果を EA と同じ形式（<銘柄>_trades.csv・_eval.csv・_bars.csv・
            _info.csv）で書く。--json PATH は指標と最初の食い違いを JSON で書く。

成績の評価はしない（取引の一致だけを見る）。優位性は検証中（結果は fusion/RESULTS.md）。
"""
import argparse
import contextlib
import io
import json
import math
import os
import sys
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from fusion import data as fd
from fusion import indicators as ind
from fusion import strategy as fs

# ---------------------------------------------------------------- EA のログ形式（FX_Fusion_EA.mq5 の FE_EvalHeader／FE_TradeHeader）
TIME_FMT = '%Y.%m.%d %H:%M'
HOUR = pd.Timedelta(hours=1)
EVAL_HEADER = ('bar_time,dir,pattern,key_time,code,price,sl,R,r_atr,depth,slope80,gap,conv,rel,T_D1,T_BIG,T_SMALL,'
               'n_sup,sup,rr_cf,tp1,S1,S2,S3,S4,S5,S6,score,phase')
TRADE_HEADER = ('entry_time,dir,entry,initial_sl,exit_time,exit_reason,R,bars_held,key_time,score,pattern,exit_price,'
                'mfe_r,mae_r,phase')
EVAL_COLS = EVAL_HEADER.split(',')
TRADE_COLS = TRADE_HEADER.split(',')
EVAL_NUM = ['price', 'sl', 'R', 'r_atr', 'depth', 'slope80', 'gap', 'conv', 'rel', 'T_D1', 'T_BIG', 'T_SMALL', 'n_sup',
            'rr_cf', 'tp1', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'score']
TRADE_NUM = ['entry', 'initial_sl', 'R', 'bars_held', 'score', 'pattern', 'exit_price', 'mfe_r', 'mae_r']

# 評価順（SPEC §8）。'OK' は最後まで通った候補（ARMED／UPDATE／LOSE）
CODE_ORDER = ['R00', 'R01A', 'R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10', 'R11', 'R12',
              'R13', 'R14', 'R15', 'R16', 'OK']
CANDIDATE = ('ARMED', 'UPDATE', 'LOSE')
T_CODES = ('T1', 'T2', 'T3', 'T4', 'T5')
# EA の SSetup.stage と同じ「どこまで計算したか」（1=depth 等、2=key、3=price/SL/R/rel、4=gap、5=支え、6=rr_cf、7=全部）
STAGE = {'R00': 0, 'R01A': 0, 'R01': 0, 'R02': 1, 'R03': 1, 'R04': 2, 'R05': 2, 'R06': 2, 'R07': 2, 'R08': 2,
         'R09': 3, 'R10': 3, 'R11': 3, 'R12': 4, 'R13': 4, 'R14': 5, 'R15': 6, 'R16': 6, 'OK': 7}
CODE_DESC = {
    'R00': '指標の準備未了', 'R01A': 'H1 版 G1 と不一致', 'R01': '4Hダウ不成立', 'R02': '押しが4H MA未達',
    'R03': '押しの内側に1H転換点なし', 'R04': '切上げ(切下げ)の崩れ', 'R05': '消化済み', 'R06': '約定済みのセットアップ',
    'R07': 'G3遅すぎ', 'R08': '4H MAが逆向き', 'R09': 'R過小', 'R10': 'R過大', 'R11': '日足逆行', 'R12': 'MA乖離',
    'R13': '1H転換型でない', 'R14': '背後の支えなし', 'R15': '反対勢力が近い', 'R16': '目標が近い',
    'ARMED': '新しい key で待機注文', 'UPDATE': '同じ key の置き直し', 'LOSE': '反対側にスコアで負け',
    'T1': '休場日', 'T2': '新規停止', 'T3': 'ロールオーバー', 'T4': '建玉あり', 'T5': '決済足',
}
# 値の食い違いの許容幅（EA は価格を小数10桁、比率を小数6桁で書く。Python の rr_cf は meta で小数2桁に丸めている）
PRICE_TOL = 1e-9
RATIO_TOL = 2e-6
FIELD_TOL = {'price': PRICE_TOL, 'sl': PRICE_TOL, 'R': PRICE_TOL, 'tp1': PRICE_TOL, 'r_atr': RATIO_TOL,
             'depth': RATIO_TOL, 'slope80': RATIO_TOL, 'gap': RATIO_TOL, 'conv': RATIO_TOL, 'rr_cf': 6e-3,
             'rel': 0, 'T_D1': 0, 'T_BIG': 0, 'T_SMALL': 0, 'n_sup': 0, 'S1': 0, 'S2': 0, 'S3': 0, 'S4': 0, 'S5': 0,
             'S6': 0, 'score': 0}
# 照合の合格基準（SPEC §18）
COUNT_TOL = 0.05
DIR_RATE_MIN = 0.90
SL_POINTS_MAX = 1.0

HINT_LABEL = {
    'rounding': '境界値の丸め（§17.6）',
    'window': '窓の長さ・始点（§17.3）',
    'dow_init': 'ダウ状態機械の初期値（§17.3）',
    'initial_state': '待機注文・約定済み集合の初期状態（§17.3）',
    'fill_order': '約定順序（§17.11）',
    'spread': 'スプレッド（§17.10・§7.5）',
    'missing_bars': '欠損足（§17.12）',
    'time_rules': '時刻ルール・暦・サーバー時間（§17.8・§2.6）',
    'real_only': '実約定だけの見送り・修正（§17.5・§17.7）',
    'end': '停止時の END 決済',
    'chain': '前の食い違いの連鎖',
    'engine': 'エンジン部の移植（mt5/engine_check/run.sh）',
}
ISSUE_LABEL = {
    'EA_ONLY': 'EA だけにある取引', 'PY_ONLY': 'Python だけにある取引', 'SHIFT': 'エントリーが1本ずれた',
    'SL': '初期 SL の差が1ポイント超', 'SL_EXACT': '初期 SL がわずかに違う（1ポイント以内）', 'ENTRY': '約定価格が違う',
    'EXIT_REASON': '決済理由が違う', 'EXIT_TIME': '決済の時刻が違う', 'R': 'R の実績が違う', 'BARS_HELD': '保有本数が違う',
    'KEY': 'key（戻り高値・安値の足）が違う', 'SCORE': 'スコアが違う', 'MFE': 'MFE/MAE が違う',
}
REAL_RELEVANT = ('SHIFT', 'SL', 'EXIT_REASON', 'EXIT_TIME', 'KEY')     # 実約定で「食い違い」とみなすもの


# ---------------------------------------------------------------- 小道具
def symbol_base(symbol):
    """銘柄名 → SPEC §10.3 の表の名前（EA の FE_SymbolBase と同じ: 大文字にし、GOLD〜 は XAUUSD、ほかは先頭6文字）"""
    s = str(symbol).strip().upper()
    if s.startswith('GOLD'):
        return 'XAUUSD'
    return s[:6]


def default_point(base):
    """1ポイント（5桁・3桁表示の一般的な口座）。--point で上書きできる"""
    if base == 'XAUUSD':
        return 0.01
    if base.endswith('JPY'):
        return 0.001
    return 0.00001


def _digits(point):
    return max(0, int(round(-math.log10(point)))) if point > 0 else 5


def _isnan(v):
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _ft(ts):
    return '' if _isnan(ts) else pd.Timestamp(ts).strftime(TIME_FMT)


def _ff(v, nd):
    return '' if _isnan(v) else f'{float(v):.{nd}f}'


def _fi(v):
    return '' if _isnan(v) else str(int(v))


def _dirname(d):
    return {1: '買い', -1: '売り'}.get(int(d), '—') if not _isnan(d) else '—'


def _patname(p):
    return {1: '①', 3: '③'}.get(int(p), '') if not _isnan(p) else ''


def _read_text(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp932'):                        # EA は FILE_ANSI（日本語 Windows なら cp932）で書く
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode('latin-1')


def _read_csv_str(path):
    df = pd.read_csv(io.StringIO(_read_text(path)), dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def parse_time(value):
    """'YYYY.MM.DD HH:MM'・'YYYY-MM-DD[ HH:MM[:SS]]' → Timestamp（空なら NaT）"""
    if _isnan(value) or str(value).strip() == '':
        return pd.NaT
    s = str(value).strip().replace('.', '-').replace('/', '-')
    try:
        return pd.Timestamp(s)
    except ValueError as e:
        raise ValueError(f'時刻を読めません: {value!r}') from e


def _parse_times(series):
    s = pd.Series(series, dtype=object).astype(str).str.strip()
    blank = s == ''
    norm = s.str.replace('.', '-', regex=False).str.replace('/', '-', regex=False)
    out = pd.to_datetime(norm.where(~blank), format='ISO8601', errors='coerce')
    bad = out.isna() & ~blank
    if bad.any():
        raise ValueError(f'時刻を読めません: {s[bad].iloc[0]!r}')
    return out.dt.as_unit('ns')


def _num(series):
    s = pd.Series(series, dtype=object).astype(str).str.strip()
    return pd.to_numeric(s.where(s != ''), errors='coerce').astype(float)


def parse_days(text):
    """'YYYY.MM.DD;YYYY.MM.DD'（, でも可）→ date の集合（EA の FE_ParseDateList と同じく8文字未満は無視）"""
    out = set()
    if not text:
        return out
    for part in str(text).replace(',', ';').split(';'):
        p = part.strip()
        if len(p) < 8:
            continue
        out.add(parse_time(p).date())
    return out


@contextlib.contextmanager
def _patched(obj, name, value):
    """obj.name を一時的に差し替える（照合の間だけ。ファイルは変更しない）"""
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


@contextlib.contextmanager
def _dict_added(dct, key, value):
    had = key in dct
    old = dct.get(key)
    dct[key] = value
    try:
        yield
    finally:
        if had:
            dct[key] = old
        else:
            dct.pop(key, None)


# ---------------------------------------------------------------- 入力の読み込み
def read_bars(path, offset_h=0):
    """MT5 の H1 足 CSV → サーバー時間の OHLC（fusion.data.load_mt5_csv と同じ読み方）。
    土日は NY+7 に換算した時刻の曜日で捨てる（EA の IsWeekendBar と同じ）。オフセット 0 なら load_mt5_csv そのもの。
    オフセットがあるときは、load_mt5_csv のサーバー時間での土日除外を止めて読み、換算後の曜日で除く
    （例: オフセット +1 の土曜 00:00 は NY+7 の金曜 23:00 なので残し、オフセット −2 の日曜 22:00 は月曜 00:00 なので残す）。"""
    if not offset_h:
        return fd.load_mt5_csv(path)
    with _patched(fd, 'drop_weekend', lambda df: df):
        raw = fd.load_mt5_csv(path)
    ny = raw.index - pd.Timedelta(hours=int(offset_h))
    return raw[ny.dayofweek < 5]


def read_info(path):
    """<銘柄>_info.csv（key,value）→ dict。値にカンマが入っても最初のカンマで分ける"""
    info = {}
    lines = _read_text(path).splitlines()
    for line in lines[1:] if lines and lines[0].strip().lower().startswith('key') else lines:
        if ',' not in line:
            continue
        k, v = line.split(',', 1)
        info[k.strip()] = v.strip()
    return info


def _kv(text):
    out = {}
    for tok in str(text or '').split():
        if '=' in tok:
            k, v = tok.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def switches_from_info(info):
    """_info.csv の switches/params → strategy.run_h1 に渡すスイッチ辞書（既定と同じものは入れない）"""
    sw = {}
    kv = _kv(info.get('switches', ''))
    flag = lambda v: str(v).strip() not in ('0', '', 'false', 'False')
    if 'g3' in kv:
        sw['g3'] = flag(kv['g3'])
    if 'd1_gate' in kv:
        sw['d1_gate'] = {'0': 'off', '1': 'strict', '2': 'soft'}.get(kv['d1_gate'], 'off')
    for k in ('gap_gate', 'clear_gate', 'support_gate', 'p3'):
        if k in kv:
            sw[k] = flag(kv[k])
    if 'cf_scope' in kv:
        sw['cf_scope'] = {'0': 'strong', '1': 'daily'}.get(kv['cf_scope'], 'strong')
    if 'sl_mode' in kv:
        sw['sl_mode'] = {'0': 'run', '1': 'node'}.get(kv['sl_mode'], 'run')
    sw = {k: v for k, v in sw.items() if fs.DEFAULT_SW.get(k) != v}
    defaults = dict(fs.CORE)
    defaults.update(fs.AUX)
    for k, v in _kv(info.get('params', '')).items():
        if k not in defaults:
            continue
        val = int(round(float(v))) if isinstance(defaults[k], int) else float(v)
        if abs(val - defaults[k]) > 1e-9:
            sw[k] = val
    return sw


def config_name(sw):
    """スイッチ辞書 → 表示用の構成名（strategy.VARIANTS に同じものがあればその名前）"""
    sw = dict(sw or {})
    if not sw:
        return 'fusion（既定）'
    for name, v in fs.VARIANTS.items():
        if v == sw:
            return name
    return 'fusion + ' + ' '.join(f'{k}={v}' for k, v in sorted(sw.items()))


def _info_switches(sw):
    S = dict(fs.DEFAULT_SW)
    S.update(sw or {})
    return ('g3=%d d1_gate=%d gap_gate=%d clear_gate=%d cf_scope=%d support_gate=%d sl_mode=%d p3=%d' % (
        int(bool(S['g3'])), {'off': 0, 'strict': 1, 'soft': 2}.get(S['d1_gate'], 0), int(bool(S['gap_gate'])),
        int(bool(S['clear_gate'])), {'strong': 0, 'daily': 1}.get(S['cf_scope'], 0), int(bool(S['support_gate'])),
        {'run': 0, 'node': 1}.get(S['sl_mode'], 0), int(bool(S['p3']))))


def _info_params(P):
    return ('N_BIG=%d N_SMALL=%d ZONE_ATR=%.4f SLOPE_MIN=%.4f ENTRY_BUF_ATR=%.4f SL_BUF_ATR=%.4f R_MIN_ATR=%.4f '
            'R_MAX_ATR=%.4f N_D1=%d TOL_LV=%.4f TOL_S=%.4f CF_MIN_TOUCH=%d RR_CF=%.4f GAP_HI=%.4f LVL_MAX_ATR=%.4f' % (
                P['N_BIG'], P['N_SMALL'], P['ZONE_ATR'], P['SLOPE_MIN'], P['ENTRY_BUF_ATR'], P['SL_BUF_ATR'],
                P['R_MIN_ATR'], P['R_MAX_ATR'], P['N_D1'], P['TOL_LV'], P['TOL_S'], P['CF_MIN_TOUCH'], P['RR_CF'],
                P['GAP_HI'], P['LVL_MAX_ATR']))


def read_trades(path):
    """EA の取引ログ → DataFrame（時刻は Timestamp、数値は float）。戻り値: (df, 実約定か)
    _trades.csv（仮想ブローカー）と _real.csv（自動売買の実約定。ticket 列がある）の両方を読む"""
    raw = _read_csv_str(path)
    need = ('entry_time', 'dir', 'initial_sl')
    miss = [c for c in need if c not in raw.columns]
    if miss:
        raise ValueError(f'{path}: 取引ログに必要な列がありません: {", ".join(miss)}（EA の <銘柄>_trades.csv を指定）')
    out = pd.DataFrame(index=range(len(raw)))
    for c in ('entry_time', 'exit_time', 'key_time'):
        out[c] = _parse_times(raw[c]) if c in raw.columns else pd.Series(pd.NaT, index=out.index, dtype='datetime64[ns]')
    out['dir'] = _num(raw['dir'])
    if out['dir'].isna().any() or not out['dir'].isin([1.0, -1.0]).all():
        raise ValueError(f'{path}: dir 列は 1 か -1 のはずです')
    out['dir'] = out['dir'].astype(int)
    for c in TRADE_NUM:
        out[c] = _num(raw[c]) if c in raw.columns else np.nan
    if out['initial_sl'].isna().any():
        raise ValueError(f'{path}: initial_sl が空の行があります')
    if out['entry_time'].isna().any():
        raise ValueError(f'{path}: entry_time が空の行があります')
    out['exit_reason'] = raw['exit_reason'] if 'exit_reason' in raw.columns else ''
    out['phase'] = raw['phase'] if 'phase' in raw.columns else ''
    real = 'ticket' in raw.columns
    return out[TRADE_COLS], real


def read_eval(path):
    """EA の評価ログ → DataFrame（bar_time・key_time は Timestamp、数値は float。空欄は NaN／''）"""
    raw = _read_csv_str(path)
    miss = [c for c in ('bar_time', 'dir', 'pattern', 'code') if c not in raw.columns]
    if miss:
        raise ValueError(f'{path}: 評価ログに必要な列がありません: {", ".join(miss)}（EA の <銘柄>_eval.csv を指定）')
    out = pd.DataFrame(index=range(len(raw)))
    out['bar_time'] = _parse_times(raw['bar_time'])
    out['dir'] = _num(raw['dir']).fillna(0).astype(int)
    out['pattern'] = _num(raw['pattern']).fillna(0).astype(int)
    out['key_time'] = _parse_times(raw['key_time']) if 'key_time' in raw.columns else pd.NaT
    out['code'] = raw['code'].astype(str)
    for c in EVAL_NUM:
        out[c] = _num(raw[c]) if c in raw.columns else np.nan
    out['sup'] = raw['sup'].astype(str) if 'sup' in raw.columns else ''
    out['phase'] = raw['phase'].astype(str) if 'phase' in raw.columns else ''
    return out[EVAL_COLS]


# ---------------------------------------------------------------- Python 側（strategy.run_h1 を同じ足で）
@dataclass
class PyRun:
    """Python 参照実装の結果。時刻はすべてサーバー時間（NY+7 ＋ offset_h）"""
    base: str
    s_nom: float
    offset_h: int
    sw: dict
    P: dict
    S: dict
    bars: pd.DataFrame                  # Python に渡した足（サーバー時間）
    trades: pd.DataFrame                # EA の _trades.csv と同じ列 ＋ entry_bar・exit_bar（足番号）
    evals: pd.DataFrame                 # EA の _eval.csv と同じ列 ＋ t（足番号）
    funnel: dict
    first: int                          # 判定を始めた足（SPEC §2.7。EA の first_eval_time）
    hc: np.ndarray
    no_new: np.ndarray
    flat: np.ndarray
    rollover: np.ndarray
    gap_before: np.ndarray
    closed: set
    early: set
    extra_closed: set
    extra_early: set
    diag: dict                          # (t, dir, pattern) → strategy の diag（途中の値）
    pend_before: list                   # 足 t の約定判定の直前にあった待機注文（setup の dict）か None
    arrays: dict                        # atr・ma80・ma480・C など（ヒントの計算用）

    def bar_of(self, ts):
        """サーバー時間の時刻 → それを含む足の番号（範囲外は -1 か len）"""
        return int(self.bars.index.searchsorted(pd.Timestamp(ts), side='right')) - 1


def _with_extra_days(orig, extra_closed, extra_early):
    def calendar_sets(sym, years):
        closed, early = orig(sym, years)
        return set(closed) | set(extra_closed), set(early) | set(extra_early)
    return calendar_sets


def run_python(bars, base, offset_h=0, sw=None, extra_closed=(), extra_early=(), s_nom=None):
    """bars（サーバー時間）で strategy.run_h1 を回し、EA のログと同じ粒度の取引一覧・評価行を作る"""
    sw = dict(sw or {})
    S = dict(fs.DEFAULT_SW)
    S.update(sw)
    if S['entry'] != 'stop' or S['expiry_emul']:
        raise ValueError('この構成（F-stop・素朴ベースライン・mincore_raw）は EA にないので照合できません')
    P = dict(fs.CORE)
    P.update(fs.AUX)
    P.update(fs.FIX)
    P.update({k: v for k, v in S.items() if k in P})
    if base not in fs.S_NOM and s_nom is None:
        raise ValueError(f'{base} は SPEC §10.3 の s_nom の表にありません。_info.csv の s_nom（--s-nom）を渡してください')
    extra_closed, extra_early = set(extra_closed or ()), set(extra_early or ())
    shift = pd.Timedelta(hours=int(offset_h))
    bars = bars[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    srv = pd.DatetimeIndex(bars.index)
    h1 = bars.copy()
    h1.index = srv - shift                                     # NY+7 にそろえて Python に渡す
    n = len(h1)
    if n == 0:
        raise ValueError('足がありません')
    events = defaultdict(list)

    def trace(kind, t, payload):
        if kind == 'eval':
            events[t].append(payload)

    with contextlib.ExitStack() as stack:
        if extra_closed or extra_early:
            stack.enter_context(_patched(fs, 'calendar_sets', _with_extra_days(fs.calendar_sets, extra_closed, extra_early)))
        if base not in fs.S_NOM:
            stack.enter_context(_dict_added(fs.S_NOM, base, float(s_nom)))
        trades, funnel = fs.run_h1(h1, base, sw, trace=trace)
        no_new, flat, rollover, gap_before = fs.time_rules(h1.index, base, S, HOUR, P['GAP_FALLBACK_H'])
        closed, early = fs.calendar_sets(base, range(h1.index[0].year, h1.index[-1].year + 2))
        s_used = float(fs.S_NOM[base])

    ny = h1.index
    O, H, L, C = (h1[k].to_numpy(dtype=float) for k in ('Open', 'High', 'Low', 'Close'))
    atr = ind.atr(H, L, C, 14)
    ma20, ma80, ma480 = ind.sma(C, 20), ind.sma(C, 80), ind.sma(C, 480)
    TD = fs.dow_machine(H, L, C, P['N_D1'])[0]
    TB = fs.dow_machine(H, L, C, P['N_BIG'])[0]
    TS = fs.dow_machine(H, L, C, P['N_SMALL'])[0]
    bs = ind.SwingBook(H, L, P['N_SMALL'], lookback=P['LB_SMALL'])
    ct = ny + HOUR
    hc = ct.hour.values + ct.minute.values / 60.0
    hc = np.where((hc == 0) & (ct.normalize() > ny.normalize()), 24.0, hc)
    first = n
    for t in range(n):                                         # strategy.run_h1 と同じ判定開始（SPEC §2.7）
        if not np.isnan(atr[t]) and not np.isnan(ma80[t]) and t >= P['SLOPE_LB'] + 80:
            first = t
            break
    if S['warmup'] is not None:
        first = S['warmup']

    # 取引 → 約定足・決済足。足 t の確定時（新規判定の時点）に建玉があるか
    pos_of = {ts: i for i, ts in enumerate(ny)}
    open_at = np.zeros(n, dtype=bool)
    tbars = []
    for tr in trades:
        te = int(tr['m_entry_idx'])
        last = str(tr['exit_reason']).split('+')[-1]
        when = tr['exit_time'] - HOUR if last in ('WEEKEND', 'END') else tr['exit_time']
        if when not in pos_of:
            raise RuntimeError(f'Python の決済時刻 {when} を足に対応づけられません')
        tx = pos_of[when]
        open_at[te:(n if last == 'END' else tx)] = True
        tbars.append((te, tx))

    def place_metrics(t, d, pattern, j_peak):
        """押しの深さ・4H MA の傾き・MA 収束（strategy.setup と同じ式。候補の行は meta が丸めてあるので計算し直す）"""
        win = slice(j_peak + 1, t + 1)
        ref = ma480 if pattern == 3 else ma80
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            if d == 1:
                depth = float(np.nanmin((L[win] - ref[win]) / atr[win]))
            else:
                depth = float(np.nanmin((ref[win] - H[win]) / atr[win]))
            conv = float(np.nanmin(np.abs(ma20[win] - ma80[win]) / atr[win]))
        slope = (ma80[t] - ma80[t - P['SLOPE_LB']]) / atr[t] * d
        return depth, slope, conv

    def base_row(t, d, pattern, code):
        r = dict.fromkeys(EVAL_COLS, np.nan)
        r.update(t=t, bar_time=srv[t], dir=d, pattern=pattern, code=code, key_time=pd.NaT, sup='', phase='REPLAY',
                 T_D1=int(TD[t]), T_BIG=int(TB[t]), T_SMALL=int(TS[t]))
        return r

    def eval_row(t, e, code_out):
        d, pattern, code = int(e['d']), int(e['pattern']), e['code']
        diag, setup = e['diag'], e['setup']
        st = STAGE['OK' if setup is not None else code]
        r = base_row(t, d, pattern, code_out)
        if st >= 1:
            if setup is None:
                r['depth'], r['slope80'], r['conv'] = float(diag['depth']), float(diag['slope']), float(diag['conv'])
            else:
                r['depth'], r['slope80'], r['conv'] = place_metrics(t, d, pattern, int(diag['j_peak']))
                m = setup['meta']
                if (round(r['depth'], 3), round(r['slope80'], 3), round(r['conv'], 3)) != (m['depth'], m['slope'], m['conv']):
                    raise RuntimeError(f'足 {t} の depth/slope/conv を strategy と同じに計算し直せません（式が変わった可能性）')
        if st >= 2:
            if setup is not None:
                j_sh = int(setup['key'][1])
            else:
                sw_ = bs.highs(t, 1) if d == 1 else bs.lows(t, 1)
                j_sh = int(sw_[0][1])
            r['key_time'] = srv[j_sh]
        if st >= 3:
            r['price'], r['sl'], r['R'] = float(diag['price']), float(diag['sl']), float(diag['R'])
            r['r_atr'] = r['R'] / atr[t]
            r['rel'] = int(TD[t] * d)
        if st >= 4 and not np.isnan(ma480[t]):
            r['gap'] = (ma80[t] - ma480[t]) * d / atr[t]
        if setup is not None:
            m = setup['meta']
            r.update(n_sup=int(m['n_sup']), sup=str(m['sup']), rr_cf=float(m['rr_cf']), tp1=float(setup['tp1']),
                     S1=m['s1'], S2=m['s2'], S3=m['s3'], S4=m['s4'], S5=m['s5'], S6=m['s6'], score=m['score'])
        elif code == 'R14':
            r.update(n_sup=0, sup='')
        return r

    # run_h1 のループ（SPEC §14）を同じ順でなぞり、待機注文の状態と見送りの理由を組み立て直す
    rows, fills, diag_store = [], {}, {}
    pend_before = [None] * n
    pend = None
    for t in range(first, n):
        if gap_before[t] and S['calendar']:                    # 1) 休場明け
            pend = None
        pend_before[t] = pend
        if pend is not None:                                   # 2) 逆指値の約定判定（待機注文があれば建玉はない）
            d0, sp = pend['dir'], pend['price']
            touched = (H[t] + s_used / 2 >= sp) if d0 == 1 else (L[t] - s_used / 2 <= sp)
            if touched:
                fills[t] = pend
                pend = None
        evs = events.get(t)
        if not evs:                                            # 5) 時刻・建玉による見送り
            if flat[t]:
                code = 'T1' if (S['calendar'] and ny[t].date() in closed) else 'T5'
            elif open_at[t]:
                code = 'T4'
            elif no_new[t]:
                code = 'T2'
            elif rollover[t]:
                code = 'T3'
            else:
                raise RuntimeError(f'足 {t}（{ny[t]}）で判定も見送りも再現できません（strategy.py の処理順が変わった可能性）')
            if code != 'T4':
                pend = None
            rows.append(base_row(t, 0, 0, code))
            continue
        if flat[t] or open_at[t] or no_new[t] or rollover[t]:
            raise RuntimeError(f'足 {t}（{ny[t]}）は見送りのはずなのに判定されています（strategy.py の処理順が変わった可能性）')
        best = None                                            # 6) 新規判定（スコアの高い方。同点は先に評価した買い）
        for e in evs:
            s = e['setup']
            if s is not None and (best is None or s['meta']['score'] > best['meta']['score']):
                best = s
        if best is None:
            action = None
            pend = None
        else:
            action = 'ARMED' if (pend is None or pend['key'] != best['key']) else 'UPDATE'
            pend = best
        for e in evs:
            code = e['code'] if e['setup'] is None else (action if e['setup'] is best else 'LOSE')
            rows.append(eval_row(t, e, code))
            diag_store[(t, int(e['d']), int(e['pattern']))] = e['diag']

    # 組み立て直しが run_h1 と同じか（約定足・理由コードの件数）
    entry_bars = sorted(te for te, _ in tbars)
    if sorted(fills) != entry_bars:
        raise RuntimeError('組み立て直した約定足が run_h1 の取引と合いません（strategy.py の処理順が変わった可能性）')
    cnt = Counter(r['code'] for r in rows)
    for code in set(funnel) | {c for c in cnt if c.startswith('R') or c == 'ARMED'}:
        if funnel.get(code, 0) != cnt.get(code, 0):
            raise RuntimeError(f'組み立て直した {code} の件数 {cnt.get(code, 0)} が run_h1 の funnel {funnel.get(code, 0)} と合いません')

    trows = []
    for tr, (te, tx) in zip(trades, tbars):
        d = int(tr['direction'])
        single = '+' not in str(tr['exit_reason'])
        trows.append(dict(
            entry_time=srv[te], dir=d, entry=float(tr['entry']), initial_sl=float(tr['initial_sl']),
            exit_time=pd.Timestamp(tr['exit_time']) + shift, exit_reason=str(tr['exit_reason']), R=float(tr['pnl_r']),
            bars_held=int(tr['bars_held']), key_time=srv[int(fills[te]['key'][1])], score=int(tr['m_score']),
            pattern=int(tr['m_pattern']),
            exit_price=(float(tr['entry']) + d * float(tr['pnl_r']) * float(tr['risk'])) if single else np.nan,
            mfe_r=float(tr['mfe_r']), mae_r=float(tr['mae_r']), phase='REPLAY', entry_bar=te, exit_bar=tx))
    tdf = pd.DataFrame(trows, columns=TRADE_COLS + ['entry_bar', 'exit_bar'])
    edf = pd.DataFrame(rows, columns=EVAL_COLS + ['t'])
    for c in ('bar_time', 'key_time'):
        edf[c] = pd.to_datetime(edf[c]).dt.as_unit('ns')
    for c in ('entry_time', 'exit_time', 'key_time'):
        tdf[c] = pd.to_datetime(tdf[c]).dt.as_unit('ns')
    for c in EVAL_NUM:
        edf[c] = edf[c].astype(float)
    bars_srv = bars.copy()
    bars_srv.index = srv
    return PyRun(base=base, s_nom=s_used, offset_h=int(offset_h), sw=sw, P=P, S=S, bars=bars_srv, trades=tdf, evals=edf,
                 funnel=dict(funnel), first=first, hc=hc, no_new=no_new, flat=flat, rollover=rollover,
                 gap_before=gap_before, closed=closed, early=early, extra_closed=extra_closed, extra_early=extra_early,
                 diag=diag_store, pend_before=pend_before,
                 arrays=dict(O=O, H=H, L=L, C=C, atr=atr, ma80=ma80, ma480=ma480, TD=TD, TB=TB, TS=TS))


# ---------------------------------------------------------------- Python の結果を EA のログ形式で書く
def eval_csv_line(r):
    """評価行 → EA の FE_EvalCsv と同じ1行"""
    code = str(r['code'])
    st = 0 if code in T_CODES else (7 if code in CANDIDATE else STAGE.get(code, 0))
    c = [_ft(r['bar_time']), _fi(r['dir']), _fi(r['pattern']), _ft(r['key_time']) if st >= 2 else '', code]
    c += [_ff(r['price'], 10), _ff(r['sl'], 10), _ff(r['R'], 10), _ff(r['r_atr'], 6)] if st >= 3 else [''] * 4
    c += [_ff(r['depth'], 6), _ff(r['slope80'], 6)] if st >= 1 else ['', '']
    c += [_ff(r['gap'], 6) if st >= 4 else '']
    c += [_ff(r['conv'], 6) if st >= 1 else '']
    c += [_fi(r['rel']) if st >= 3 else '']
    c += [_fi(r['T_D1']), _fi(r['T_BIG']), _fi(r['T_SMALL'])]
    c += [_fi(r['n_sup']), '' if _isnan(r['n_sup']) else str(r['sup'])] if st >= 5 else ['', '']
    c += [_ff(r['rr_cf'], 6) if st >= 6 else '']
    c += [_ff(r['tp1'], 10)] + [_fi(r[k]) for k in ('S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'score')] if st >= 7 else [''] * 8
    c += [str(r['phase']) or 'REPLAY']
    return ','.join(c)


def trade_csv_line(r):
    """取引 → EA の FE_TradeCsv と同じ1行"""
    return ','.join([_ft(r['entry_time']), _fi(r['dir']), _ff(r['entry'], 10), _ff(r['initial_sl'], 10),
                     _ft(r['exit_time']), str(r['exit_reason']), _ff(r['R'], 8), _fi(r['bars_held']),
                     _ft(r['key_time']), _fi(r['score']), _fi(r['pattern']), _ff(r['exit_price'], 10),
                     _ff(r['mfe_r'], 4), _ff(r['mae_r'], 4), str(r['phase']) or 'REPLAY'])


def write_python_logs(py, out_dir, tag=None):
    """Python の結果を EA と同じ形式・同じ名前（<tag>_trades.csv・_eval.csv・_bars.csv・_info.csv）で書く。
    戻り値: {'trades': path, 'eval': path, 'bars': path, 'info': path}"""
    tag = tag or py.base
    os.makedirs(out_dir, exist_ok=True)
    paths = {k: os.path.join(out_dir, f'{tag}_{k}.csv') for k in ('trades', 'eval', 'bars', 'info')}
    with open(paths['trades'], 'w', encoding='utf-8', newline='') as f:
        f.write(TRADE_HEADER + '\r\n')
        for r in py.trades.to_dict('records'):
            f.write(trade_csv_line(r) + '\r\n')
    with open(paths['eval'], 'w', encoding='utf-8', newline='') as f:
        f.write(EVAL_HEADER + '\r\n')
        for r in py.evals.to_dict('records'):
            f.write(eval_csv_line(r) + '\r\n')
    with open(paths['bars'], 'w', encoding='utf-8', newline='') as f:
        f.write('Time,Open,High,Low,Close\r\n')
        for ts, o, h, l, c in zip(py.bars.index, *(py.bars[k].to_numpy(float) for k in ('Open', 'High', 'Low', 'Close'))):
            f.write(f'{_ft(ts)},{o:.10f},{h:.10f},{l:.10f},{c:.10f}\r\n')
    days = lambda s: ';'.join(sorted(d.strftime('%Y.%m.%d') for d in s))
    info = [('ea', 'fusion.strategy.run_h1（Python 参照実装を EA の形式で書き出したもの）'), ('symbol', tag), ('base', py.base),
            ('s_nom', f'{py.s_nom:.8f}'), ('is_xau', '1' if py.base == 'XAUUSD' else '0'),
            ('server_offset_h', str(py.offset_h)), ('first_bar_time', _ft(py.bars.index[0])),
            ('first_eval_time', _ft(py.bars.index[py.first]) if py.first < len(py.bars) else ''),
            ('bars_loaded', str(len(py.bars))), ('history_bars_input', str(len(py.bars))), ('config', config_name(py.sw)),
            ('switches', _info_switches(py.sw)), ('params', _info_params(py.P)),
            ('extra_closed', days(py.extra_closed)), ('extra_early', days(py.extra_early))]
    with open(paths['info'], 'w', encoding='utf-8', newline='') as f:
        f.write('key,value\r\n')
        for k, v in info:
            f.write(f'{k},{v}\r\n')
    return paths


# ---------------------------------------------------------------- 取引の比較（SPEC §18）
@dataclass
class TradeCmp:
    real: bool
    point: float
    n_ea: int
    n_py: int
    pairs: list                 # dict(ea, py, shift, issues, time)
    ea_only: list               # EA の行番号
    py_only: list               # Python の行番号
    opposite: list              # (EA の行, Python の行): ±1本以内で方向だけ逆
    out_of_range: int           # 足の範囲外で比べなかった EA の取引
    count_diff: float
    count_ok: bool
    dir_rate: float
    dir_ok: bool
    sl_max_pts: float
    sl_over: int
    sl_ok: bool
    exit_match: int
    exit_rate: float
    exact: object               # 完全一致か（実約定では None）
    issue_count: Counter
    mismatches: list            # 時刻順の食い違い dict(kind, time, ea, py, issues)

    @property
    def passed(self):
        return self.count_ok and self.dir_ok and self.sl_ok


def _reason_equal(ea_reason, py_reason, real):
    a, b = str(ea_reason), str(py_reason)
    if a == b:
        return True
    if real and b == 'SL_gap' and a in ('SL', 'TRAIL'):       # 実約定では窓開けも DEAL_REASON_SL で記録される
        return True
    return False


def _ea_bars(ea, index, real):
    """EA の取引の約定足・決済足（Python の足番号）。範囲外の約定は -1"""
    n = len(index)
    end = index[-1] + HOUR
    eb, xb = [], []
    for r in ea.itertuples(index=False):
        et = r.entry_time
        b = int(index.searchsorted(et, side='right')) - 1
        eb.append(b if (0 <= b and et < end) else -1)
        xt = r.exit_time
        if _isnan(xt):
            xb.append(np.nan)
            continue
        if not real and str(r.exit_reason).split('+')[-1] in ('WEEKEND', 'END'):
            xt = xt - HOUR                                     # 確定時刻で書いてある → その足
        x = int(index.searchsorted(xt, side='right')) - 1
        xb.append(float(min(max(x, -1), n)))
    return np.array(eb, dtype=int), np.array(xb, dtype=float)


def compare_trades(ea, py, index, point, real=False, t_from=None, t_to=None):
    """EA の取引一覧と Python の取引一覧を突き合わせる。index は Python に渡した足（サーバー時間）"""
    ea = ea.reset_index(drop=True).copy()
    pyt = py.reset_index(drop=True)
    ea['entry_bar'], ea['exit_bar'] = _ea_bars(ea, index, real)
    out_of_range = int((ea['entry_bar'] < 0).sum())
    by = defaultdict(list)
    for j, r in enumerate(pyt.itertuples(index=False)):
        by[(int(r.entry_bar), int(r.dir))].append(j)
    used, pairs, rest = set(), [], []
    order = sorted((i for i in range(len(ea)) if ea.at[i, 'entry_bar'] >= 0), key=lambda i: (ea.at[i, 'entry_time'], i))
    for i in order:                                            # 1) 同じ足・同じ方向
        j = next((j for j in by.get((int(ea.at[i, 'entry_bar']), int(ea.at[i, 'dir'])), []) if j not in used), None)
        if j is None:
            rest.append(i)
        else:
            used.add(j)
            pairs.append((i, j))
    ea_only = []
    for i in rest:                                             # 2) ±1本・同じ方向
        j = None
        for db in (-1, 1):
            j = next((j for j in by.get((int(ea.at[i, 'entry_bar']) + db, int(ea.at[i, 'dir'])), []) if j not in used), None)
            if j is not None:
                break
        if j is None:
            ea_only.append(i)
        else:
            used.add(j)
            pairs.append((i, j))
    py_only = [j for j in range(len(pyt)) if j not in used]

    lo = pd.Timestamp(t_from) if t_from is not None else None
    hi = pd.Timestamp(t_to) if t_to is not None else None
    inside = lambda ts: (lo is None or ts >= lo) and (hi is None or ts < hi)
    tol_sl = point * SL_POINTS_MAX * (1 + 1e-6)
    pair_rows, sl_pts, exit_ok = [], [], 0
    for i, j in pairs:
        e, p = ea.iloc[i], pyt.iloc[j]
        tm = min(e['entry_time'], p['entry_time'])
        if not inside(tm):
            continue
        issues = []
        shift = int(e['entry_bar']) - int(p['entry_bar'])
        if shift:
            issues.append('SHIFT')
        dsl = abs(float(e['initial_sl']) - float(p['initial_sl']))
        sl_pts.append(dsl / point)
        if dsl > tol_sl:
            issues.append('SL')
        elif not real and dsl > PRICE_TOL:
            issues.append('SL_EXACT')
        rok = _reason_equal(e['exit_reason'], p['exit_reason'], real)
        exit_ok += int(rok)
        if not rok:
            issues.append('EXIT_REASON')
        if real:
            if not _isnan(e['exit_bar']) and abs(e['exit_bar'] - p['exit_bar']) > 1:
                issues.append('EXIT_TIME')
        else:
            if _isnan(e['exit_time']) or e['exit_time'] != p['exit_time']:
                issues.append('EXIT_TIME')
            if _isnan(e['entry']) or abs(e['entry'] - p['entry']) > PRICE_TOL:
                issues.append('ENTRY')
            if _isnan(e['R']) or abs(e['R'] - p['R']) > 1e-6:
                issues.append('R')
            if not _isnan(e['bars_held']) and int(e['bars_held']) != int(p['bars_held']):
                issues.append('BARS_HELD')
            if not _isnan(e['score']) and int(e['score']) != int(p['score']):
                issues.append('SCORE')
            if (not _isnan(e['mfe_r']) and abs(e['mfe_r'] - p['mfe_r']) > 1.5e-4) or \
                    (not _isnan(e['mae_r']) and abs(e['mae_r'] - p['mae_r']) > 1.5e-4):
                issues.append('MFE')
        if not _isnan(e['key_time']) and not _isnan(p['key_time']) and e['key_time'] != p['key_time']:
            issues.append('KEY')
        pair_rows.append(dict(ea=i, py=j, shift=shift, issues=issues, time=tm))
    ea_only = [i for i in ea_only if inside(ea.at[i, 'entry_time'])]
    py_only = [j for j in py_only if inside(pyt.at[j, 'entry_time'])]
    opposite, taken = [], set()
    for i in ea_only:
        for j in py_only:
            if j not in taken and abs(int(ea.at[i, 'entry_bar']) - int(pyt.at[j, 'entry_bar'])) <= 1 \
                    and int(ea.at[i, 'dir']) != int(pyt.at[j, 'dir']):
                opposite.append((i, j))
                taken.add(j)
                break
    n_pairs = len(pair_rows)
    n_ea, n_py = n_pairs + len(ea_only), n_pairs + len(py_only)
    count_diff = (n_ea - n_py) / n_py if n_py else (0.0 if n_ea == 0 else math.inf)
    denom = max(n_ea, n_py)
    dir_rate = n_pairs / denom if denom else 1.0
    sl_over = sum(1 for v in sl_pts if v > SL_POINTS_MAX * (1 + 1e-6))
    relevant = (lambda iss: [x for x in iss if x in REAL_RELEVANT]) if real else (lambda iss: list(iss))
    issue_count = Counter(x for pr in pair_rows for x in pr['issues'])
    issue_count.update({'EA_ONLY': len(ea_only), 'PY_ONLY': len(py_only)})
    issue_count = Counter({k: v for k, v in issue_count.items() if v})
    mism = [dict(kind='EA_ONLY', time=ea.at[i, 'entry_time'], ea=i, py=None, issues=['EA_ONLY']) for i in ea_only]
    mism += [dict(kind='PY_ONLY', time=pyt.at[j, 'entry_time'], ea=None, py=j, issues=['PY_ONLY']) for j in py_only]
    for pr in pair_rows:
        iss = relevant(pr['issues'])
        if iss:
            mism.append(dict(kind=iss[0], time=pr['time'], ea=pr['ea'], py=pr['py'], issues=iss))
    mism.sort(key=lambda m: (m['time'], 0 if m['ea'] is None or m['py'] is None else 1))
    exact = None if real else (not ea_only and not py_only and all(not pr['issues'] for pr in pair_rows))
    return TradeCmp(real=real, point=point, n_ea=n_ea, n_py=n_py, pairs=pair_rows, ea_only=ea_only, py_only=py_only,
                    opposite=opposite, out_of_range=out_of_range, count_diff=count_diff,
                    count_ok=abs(count_diff) <= COUNT_TOL + 1e-12, dir_rate=dir_rate,
                    dir_ok=dir_rate >= DIR_RATE_MIN - 1e-12, sl_max_pts=max(sl_pts) if sl_pts else 0.0, sl_over=sl_over,
                    sl_ok=sl_over == 0, exit_match=exit_ok, exit_rate=exit_ok / n_pairs if n_pairs else 1.0,
                    exact=exact, issue_count=issue_count, mismatches=mism), ea


# ---------------------------------------------------------------- 評価ログの比較（診断用）
@dataclass
class EvalCmp:
    n_ea: int
    n_py: int
    n_union: int
    n_match: int
    only_ea: int
    only_py: int
    duplicates: int
    confusion: Counter          # (EA のコード, Python のコード) → 件数（食い違った行だけ）
    funnel_ea: Counter
    funnel_py: Counter
    field_mismatch: Counter     # コードが同じ行での値の食い違い（列ごと）
    tstate_rows: int            # T_D1/T_BIG/T_SMALL が違う行
    tstate_last: object         # T 状態が違った最後の足（始点が違うときの「そろい始め」の目安）か None
    offset_shift: object        # T1/T2/T3/T5 の行が最もよく合う時間のずれ（EA − Python）。0 か None ならずれなし
    bars_only_ea: list          # EA にだけ行がある足（サーバー時間）
    bars_only_py: list
    first_code: object          # dict(bar_time, rows, index) か None
    first_field: object         # dict(bar_time, fields, index) か None
    merged: pd.DataFrame

    @property
    def rate(self):
        return self.n_match / self.n_union if self.n_union else 1.0


def _vals_equal(a, b, tol):
    if _isnan(a) or _isnan(b):
        return True                                            # 片方しか値がない列は比べない
    return abs(float(a) - float(b)) <= tol


def _offset_shift(ea, py):
    """時刻による見送り（T1・T2・T3・T5）の行が最もよく合う時間のずれ k（EA の時刻 ＝ Python の時刻 ＋ k）。
    k≠0 なら、Python に渡したオフセットが EA の InpServerOffsetHours と k 時間違う疑い。行が少なければ None"""
    T = ['T1', 'T2', 'T3', 'T5']
    a, b = ea[ea['code'].isin(T)], py[py['code'].isin(T)]
    if len(a) < 5 or len(b) < 5:
        return None
    A = set(zip(a['bar_time'], a['code']))
    score = {}
    for k in range(-3, 4):
        B = set(zip(b['bar_time'] + k * HOUR, b['code']))
        score[k] = len(A & B) / len(A | B)
    best = max(score, key=lambda k: (score[k], -abs(k)))
    return best if best != 0 and score[best] > score[0] + 0.1 else 0


def compare_evals(ea, py, t_from=None, t_to=None):
    """足ごと・方向ごと・パターンごとに、EA と Python の評価行を突き合わせる"""
    def win(df):
        m = pd.Series(True, index=df.index)
        if t_from is not None:
            m &= df['bar_time'] >= pd.Timestamp(t_from)
        if t_to is not None:
            m &= df['bar_time'] < pd.Timestamp(t_to)
        return df[m]
    key = ['bar_time', 'dir', 'pattern']
    ea = win(ea).copy()
    py = win(py).copy()
    for df in (ea, py):
        df['bar_time'] = pd.to_datetime(df['bar_time']).dt.as_unit('ns')
        df['key_time'] = pd.to_datetime(df['key_time']).dt.as_unit('ns')
    dup = ea.duplicated(key, keep='last')
    ea = ea[~dup]
    cols = [c for c in EVAL_COLS if c not in key]
    m = py[key + cols + ['t']].merge(ea[key + cols], on=key, how='outer', suffixes=('_py', '_ea'), indicator=True)
    m['_ord'] = m['dir'].map({1: 0, -1: 1, 0: 2}).fillna(3)
    m = m.sort_values(['bar_time', '_ord', 'pattern'], kind='mergesort').reset_index(drop=True)
    both = (m['_merge'] == 'both').to_numpy()
    code_eq = both & (m['code_py'].astype(str) == m['code_ea'].astype(str)).to_numpy()
    confusion = Counter()
    for a, b, mg in zip(m['code_ea'], m['code_py'], m['_merge']):
        if mg != 'both' or a != b:
            confusion[(a if mg != 'left_only' else '（なし）', b if mg != 'right_only' else '（なし）')] += 1
    field_mis = Counter()
    bad_field = np.zeros(len(m), dtype=bool)
    bad_cols = [[] for _ in range(len(m))]
    tstate = np.zeros(len(m), dtype=bool)
    for col, tol in list(FIELD_TOL.items()) + [('key_time', None), ('sup', None)]:
        a, b = m[col + '_ea'], m[col + '_py']
        if col == 'key_time':
            neq = a.notna() & b.notna() & (a != b)
        elif col == 'sup':
            neq = m['n_sup_ea'].notna() & m['n_sup_py'].notna() & (a.fillna('').astype(str) != b.fillna('').astype(str))
        else:
            av, bv = a.astype(float), b.astype(float)
            if col == 'rr_cf':
                av, bv = av.clip(upper=99.0), bv.clip(upper=99.0)
            neq = av.notna() & bv.notna() & ((av - bv).abs() > tol)
        neq = (neq.to_numpy() & code_eq) if col not in ('T_D1', 'T_BIG', 'T_SMALL') else (neq.to_numpy() & both)
        if col in ('T_D1', 'T_BIG', 'T_SMALL'):
            tstate |= neq
        if neq.any():
            field_mis[col] = int(neq.sum())
            bad_field |= neq
            for k in np.flatnonzero(neq):
                bad_cols[k].append(col)
    first_code = first_field = None
    bad = np.flatnonzero(~code_eq)
    if len(bad):
        bt = m.at[int(bad[0]), 'bar_time']
        first_code = dict(bar_time=bt, rows=m[m['bar_time'] == bt], index=int(bad[0]))
    badf = np.flatnonzero(bad_field)
    if len(badf):
        k = int(badf[0])
        first_field = dict(bar_time=m.at[k, 'bar_time'], fields=bad_cols[k], index=k)
    ea_b, py_b = set(ea['bar_time']), set(py['bar_time'])
    tlast = m.loc[tstate, 'bar_time'].max() if tstate.any() else None
    return EvalCmp(n_ea=len(ea), n_py=len(py), n_union=len(m), n_match=int(code_eq.sum()),
                   only_ea=int((m['_merge'] == 'right_only').sum()), only_py=int((m['_merge'] == 'left_only').sum()),
                   duplicates=int(dup.sum()), confusion=confusion, funnel_ea=Counter(ea['code']),
                   funnel_py=Counter(py['code']), field_mismatch=field_mis, tstate_rows=int(tstate.sum()),
                   tstate_last=tlast, offset_shift=_offset_shift(ea, py), bars_only_ea=sorted(ea_b - py_b),
                   bars_only_py=sorted(py_b - ea_b), first_code=first_code, first_field=first_field, merged=m)


# ---------------------------------------------------------------- SPEC §17 の分類のヒント
@dataclass
class Ctx:
    py: PyRun
    point: float
    real: bool
    start_aligned: object       # True / False / None（分からない）
    start_note: str
    info: dict
    ecmp: object = None
    ea_eval: object = None


def _hint(tag, text):
    return dict(tag=tag, label=HINT_LABEL[tag], text=text)


def _dedup(hints):
    seen, out = set(), []
    for h in hints:
        k = (h['tag'], h['text'])
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out


def _near(v, thr):
    return not _isnan(v) and abs(float(v) - thr) <= 2e-6 * max(1.0, abs(thr))


def _missing_hours(py, lo, hi):
    """足 lo〜hi の間で、休場明け（12時間以上）ではないのに1時間以上空いたところ"""
    idx = py.bars.index
    out = []
    for i in range(max(lo, 1), min(hi, len(idx) - 1) + 1):
        gap = int(round((idx[i] - idx[i - 1]) / HOUR)) - 1
        if gap >= 1 and not py.gap_before[i]:
            out.append((idx[i - 1], idx[i], gap))
    return out


def _rule_desc(py, t):
    parts = [f'確定 hc={py.hc[t]:g}']
    d = (py.bars.index[t] - pd.Timedelta(hours=py.offset_h)).date()
    if d in py.closed:
        parts.append('休場日')
    elif d in py.early:
        parts.append('早仕舞い日')
    if py.flat[t]:
        parts.append('全決済の足')
    if py.no_new[t]:
        parts.append('新規停止')
    if py.rollover[t]:
        parts.append('ロールオーバー')
    if py.gap_before[t]:
        parts.append('休場明け（直前に12時間以上の空き）')
    return '、'.join(parts)


def _eval_rows_at(df, t_time, d=None):
    if df is None:
        return []
    sel = df[df['bar_time'] == t_time]
    if d is not None:
        sel = sel[(sel['dir'] == d) | (sel['dir'] == 0)]
    return sel.to_dict('records')


def _time_hint(t, ctx, what):
    """時刻ルールが絡む食い違い（サーバー時間のずれ・夏時間・暦）"""
    py = ctx.py
    msg = f'{what}（{_rule_desc(py, t)}）。'
    sug = None if ctx.ecmp is None else ctx.ecmp.offset_shift
    if sug:
        msg += (f'評価ログの T コードは Python を {sug:+d} 時間ずらすと最もよく合う → --offset {py.offset_h + sug} を試す'
                '（EA の InpServerOffsetHours と同じ値にする）。')
    else:
        msg += '--offset（EA の InpServerOffsetHours）と、ブローカーの夏時間の切替が NY とずれる週でないかを確認。'
    if py.extra_closed or py.extra_early:
        msg += '追加の暦（extra_closed/early）の日付も確認。'
    else:
        msg += 'ブローカー固有の休場日・早仕舞い日は、EA の InpExtraClosedDays/EarlyDays と --extra-closed/--extra-early に同じ日付を入れる。'
    return _hint('time_rules', msg)


def _context_hints(t, ctx):
    """どの食い違いにも共通の状況（始点・読込本数・欠損足・足の集合の違い）"""
    py = ctx.py
    out = []
    need = py.P['LB_D1'] + py.P['N_D1']
    since = t - py.first
    if ctx.start_aligned is False:
        out.append(_hint('window', f'Python の始点が EA の最初の足と違う（{ctx.start_note}）。始点から {since} 本目なので、'
                                   f'D1 帳簿（{need} 本）・SMA480・持続型ダウ状態機械・待機注文と約定済み集合の初期状態がずれうる。'
                                   'EA の <銘柄>_bars.csv と _info.csv を渡すと始点がそろう'))
        bl = ctx.info.get('bars_loaded')
        if bl and str(bl).isdigit() and int(bl) < need:
            out.append(_hint('window', f'EA の読込本数 {bl} 本は D1 帳簿の必要本数 {need} 本より少ない（InpHistoryBars を 10000 以上に）'))
    elif ctx.start_aligned is None and since < need:
        out.append(_hint('window', f'EA の最初の足が分からない（_info.csv なし）。足の CSV が EA の読込より前から始まっていると、'
                                   f'始点から {need} 本までは D1 帳簿・ダウ状態機械の初期値がずれうる'))
    miss = _missing_hours(py, t - 120, t)
    if miss:
        ex = '、'.join(f'{_ft(a)}→{_ft(b)}（{g}本）' for a, b, g in miss[:3])
        out.append(_hint('missing_bars', f'直近120本に休場明けではない欠けがある: {ex}。ティックのない時間の足は作られない。'
                                         'EA と Python に同じ足を渡したか（EA の _bars.csv か）を確認'))
    if ctx.ecmp is not None:
        near_bars = [b for b in ctx.ecmp.bars_only_ea + ctx.ecmp.bars_only_py if abs((b - py.bars.index[t]) / HOUR) <= 400]
        if near_bars:
            out.append(_hint('missing_bars', f'評価ログの足の集合が違う（例: {_ft(near_bars[0])}）。EA だけにある足 '
                                             f'{len(ctx.ecmp.bars_only_ea)}・Python だけにある足 {len(ctx.ecmp.bars_only_py)}'))
    return out


def _bars_suspect(ctx):
    """EA と Python で足そのものや始点が違う疑いがあるか"""
    return ctx.start_aligned is not True or (ctx.ecmp is not None and bool(ctx.ecmp.bars_only_ea or ctx.ecmp.bars_only_py))


def _value_diffs(ea_row, py_row):
    """同じ足・方向の評価行で、両方にある値のうち違うもの → [(列, EA, Python)]"""
    out = []
    if ea_row is None or py_row is None:
        return out
    for col in ('key_time', 'slope80', 'depth', 'conv', 'price', 'sl', 'r_atr', 'gap', 'rel', 'rr_cf', 'score'):
        a, b = ea_row.get(col), py_row.get(col)
        if _isnan(a) or _isnan(b):
            continue
        if col == 'key_time':
            if pd.Timestamp(a) != pd.Timestamp(b):
                out.append((col, _ft(a), _ft(b)))
            continue
        av, bv = float(a), float(b)
        if col == 'rr_cf':
            av, bv = min(av, 99.0), min(bv, 99.0)
        if abs(av - bv) > FIELD_TOL[col]:
            out.append((col, av, bv))
    return out


def _value_hint(diffs, ctx):
    fmt = lambda v: v if isinstance(v, str) else f'{v:.9g}'
    names = '、'.join(f'{c} EA {fmt(a)} / Python {fmt(b)}' for c, a, b in diffs[:4])
    cols = {c for c, _, _ in diffs}
    what = []
    if 'key_time' in cols:
        what.append('SMALL 帳簿（1H の戻り高値・安値）')
    if cols & {'slope80', 'gap', 'conv'}:
        what.append('移動平均・ATR')
    elif 'depth' in cols:
        what.append('押しの起点（BIG 帳簿）か足の安値・高値')
    if cols & {'price', 'sl', 'r_atr'} and not cols & {'slope80', 'gap', 'conv'}:
        what.append('SH・runLow・ATR')
    if 'rel' in cols:
        what.append('日足のダウ状態（T_D1）')
    src = '・'.join(what) or '途中の値'
    if _bars_suspect(ctx):
        return _hint('window' if ctx.start_aligned is not True else 'missing_bars',
                     f'途中の値が違う（{names}）。{src}が違う。足の集合か始点が EA と違う疑い')
    return _hint('engine', f'同じ足から回したのに途中の値が違う（{names}）。{src}の計算（EA の判定エンジン部）を確認')


# 境界値でないときに、その理由コードが何で決まるか
CODE_SOURCE = {
    'R00': ('window', '指標の準備（ATR14・SMA80・SMA80[t−12]）が片方だけ済んでいない。始点の違いか、ATR が 0（値の動かない足が続いた）'),
    'R01': ('window', 'G1 は BIG 帳簿（深さ12・3000本）の直近2つの高値・安値と終値で決まる。帳簿の範囲・フラクタルの不等号'
                      '（新しい側は厳密、古い側は非厳密。§17.4）・同値の高値安値を確認'),
    'R03': ('window', '1H の転換点は SMALL 帳簿（深さ3・400本）で決まる。帳簿の範囲・フラクタルの不等号（§17.4）を確認'),
    'R06': ('initial_state', '約定済み集合（1セットアップにつき約定1回）が違う。どちらかで先に同じ key が約定したか、始点が違う'),
    'R11': ('dow_init', '日足逆行（R11）は持続型ダウ状態機械 T_D1 で決まる'),
    'R13': ('dow_init', '1H 転換型（R13）は持続型ダウ状態機械 T_SMALL で決まる'),
    'R14': ('window', '背後の支えは節目（BIG 1200本・D1 2880本の窓のスイング）で決まる。窓と帳簿の範囲を確認'),
    'R15': ('window', '反対勢力は節目（BIG 1200本・D1 2880本の窓）と SMA480 で決まる'),
    'R16': ('window', '目標は節目と SMA480 で決まる'),
}
# EA がその段階まで計算して書く値（両側にあれば「同じ値なのに判定が違う」を言える）
STAGE_VALUE = {'R02': 'depth', 'R08': 'slope80', 'R09': 'r_atr', 'R10': 'r_atr', 'R12': 'gap', 'R15': 'rr_cf'}


def _boundary_hints(code, d, pattern, t, ea_row, py_row, diag, ctx):
    """どちらかが code で落ち、もう一方は通ったとき、その判定の値が閾値すれすれか（§17.6）"""
    py, P = ctx.py, ctx.py.P
    A = py.arrays
    out = []
    val = lambda r, c: None if r is None else r.get(c)

    def near_both(col, thr, label):
        for side, r in (('EA', ea_row), ('Python', py_row)):
            v = val(r, col)
            if _near(v, thr):
                out.append(_hint('rounding', f'{label}={float(v):.9g}（{side}）が閾値 {thr:g} とほぼ同じ。判定は生の double で行う'
                                             '（NormalizeDouble を使っていないか）。移動平均・ATR の最下位桁の差でも割れうる'))
                return
    if code == 'R02':
        near_both('depth', P['ZONE_ATR'], 'depth')
    elif code == 'R08':
        near_both('slope80', P['SLOPE_MIN'], 'slope80')
    elif code == 'R09':
        near_both('r_atr', P['R_MIN_ATR'], 'R/ATR')
    elif code == 'R10':
        rel = val(py_row, 'rel')
        soft = py.S['d1_gate'] == 'soft' and not _isnan(rel) and int(rel) == -1
        near_both('r_atr', P['R_MAX_ATR'] * (0.5 if soft else 1.0), 'R/ATR')
    elif code == 'R12':
        near_both('gap', P['GAP_HI'], 'gap')
    elif code == 'R15':
        near_both('rr_cf', P['RR_CF'], 'rr_cf')
    elif code == 'R07' and diag and 'sh' in diag:
        ref = A['ma480'] if pattern == 3 else A['ma80']
        v = (diag['sh'] - ref[t]) * d / A['atr'][t]
        if _near(v, P['LVL_MAX_ATR']):
            out.append(_hint('rounding', f'G3 の距離 {v:.9g} が閾値 {P["LVL_MAX_ATR"]:g} とほぼ同じ'))
    elif code == 'R04' and diag and 'run_ext' in diag and 'l0' in diag:
        if abs(diag['run_ext'] - diag['l0']) <= ctx.point * 0.5:
            out.append(_hint('rounding', f'切上げ安値（runLow={diag["run_ext"]}）と直前の安値 L0={diag["l0"]} が同値。'
                                         '不等号の向き（買いは runLow > L0 で成立）と足の値を確認'))
    elif code == 'R05' and diag and 'sh' in diag:
        kt = val(py_row, 'key_time')
        if _isnan(kt):
            kt = val(ea_row, 'key_time')
        if not _isnan(kt):
            j = py.bar_of(kt)
            if 0 <= j < t:
                seg = A['C'][j + 1:t + 1]
                ext = float(seg.max() if d == 1 else seg.min())
                if abs(ext - diag['sh']) <= ctx.point * 0.5:
                    out.append(_hint('rounding', f'戻り高値（安値）{diag["sh"]} と、その後の終値の極値 {ext} が同値。'
                                                 '「終値で越えた」の判定（厳密な不等号）を確認'))
    return out


def _bar_codes(df, bt):
    return [str(r['code']) for r in _eval_rows_at(df, bt)] if df is not None else []


def _shifted_t(ctx, t, ea_t, py_t):
    """T コードの食い違いが「1時間ずれ」で説明できるか（EA の T が Python の隣の足にある、またはその逆）"""
    py = ctx.py
    for k in (t - 1, t + 1):
        if 0 <= k < len(py.bars):
            bt = py.bars.index[k]
            if ea_t and set(ea_t) & set(c for c in _bar_codes(py.evals, bt) if c in T_CODES):
                return True
            if py_t and ctx.ea_eval is not None and set(py_t) & set(c for c in _bar_codes(ctx.ea_eval, bt) if c in T_CODES):
                return True
    return False


def eval_hints(ea_row, py_row, t, ctx):
    """評価行の食い違い → ヒントの一覧（可能性の高い順）。ea_row / py_row は片方が None でもよい"""
    py = ctx.py
    hints = []
    explained = False
    ref = ea_row if ea_row is not None else py_row
    d, pattern = int(ref['dir']), int(ref['pattern'])
    a = None if ea_row is None else str(ea_row['code'])
    b = None if py_row is None else str(py_row['code'])
    diag = py.diag.get((t, d, pattern))
    bt = py.bars.index[t]
    ea_codes, py_codes = _bar_codes(ctx.ea_eval, bt), _bar_codes(py.evals, bt)
    ea_t = [c for c in ea_codes if c in T_CODES]
    py_t = [c for c in py_codes if c in T_CODES]
    if ea_t != py_t:
        what = f'見送りの理由が違う（EA {"・".join(ea_codes) or "行なし"} / Python {"・".join(py_codes) or "行なし"}）'
        if 'T4' in ea_t + py_t:
            hints.append(_hint('chain', f'{what}。片方だけ建玉を持っている（T4）。取引の食い違い（約定・決済）が先にある'))
        else:
            if _shifted_t(ctx, t, ea_t, py_t):
                what += '。隣の足では同じ見送りが出ている＝時刻ルールが1時間ずれている'
            hints.append(_time_hint(t, ctx, what))
        explained = True
    elif a is None or b is None:
        if pattern == 3:
            hints.append(_hint('engine', '③（パターン3）の行が片方だけにある。構成（_info.csv の switches の p3）がそろっているか、'
                                         '①の候補の有無が違わないかを確認'))
        else:
            hints.append(_hint('engine', '同じ足で評価した方向・パターンの組が違う'))
        explained = True
    else:
        ca = 'OK' if a in CANDIDATE else a
        cb = 'OK' if b in CANDIDATE else b
        if ca == 'OK' and cb == 'OK':
            if {a, b} == {'ARMED', 'UPDATE'}:
                hints.append(_hint('initial_state', '待機注文の有無・key が違う（前の足で片方だけ取消・約定・休場明けの取消があった、'
                                                    'または始点の初期状態が違う）。この足より前の食い違いを先に見る'))
            else:
                s4 = not _vals_equal(ea_row.get('S4'), py_row.get('S4'), 0)
                hints.append(_hint('dow_init' if s4 else 'rounding',
                                   '両方向が成立し、スコアの勝ち負けが違う。S4（日足との関係 rel＝T_D1）が違えばダウ状態機械の初期値、'
                                   'それ以外は S1（slope≥0.10）・S5（rr_cf 1/2/3）・S2（depth≤0）・S6（conv≤0.5）の境界'))
            explained = True
        elif ca in CODE_ORDER and cb in CODE_ORDER:
            dec = ca if CODE_ORDER.index(ca) < CODE_ORDER.index(cb) else cb
            bh = _boundary_hints(dec, d, pattern, t, ea_row, py_row, diag, ctx)
            hints += bh
            diffs = _value_diffs(ea_row, py_row)
            if diffs:
                hints.append(_value_hint(diffs, ctx))
            elif not bh:
                if dec in CODE_SOURCE:
                    hints.append(_hint(*CODE_SOURCE[dec]))
                col = STAGE_VALUE.get(dec)
                if col and not _isnan(ea_row.get(col)) and not _isnan(py_row.get(col)):
                    hints.append(_hint('engine', f'両側の {col} は同じ（{float(py_row[col]):.9g}）で閾値からも離れているのに、'
                                                 f'{dec}（{CODE_DESC.get(dec, "")}）の判定だけが違う。EA の判定式・不等号の移植を確認'))
                elif not _bars_suspect(ctx) and dec not in ('R06', 'R11', 'R13'):
                    hints.append(_hint('engine', f'足と始点は EA と同じなので、{dec}（{CODE_DESC.get(dec, "")}）を決める計算'
                                                 '（帳簿・指標・判定式）の移植を確認'))
            explained = True
    if ea_row is not None and py_row is not None:
        diff = [c for c in ('T_D1', 'T_BIG', 'T_SMALL') if not _vals_equal(ea_row.get(c), py_row.get(c), 0)]
        if diff:
            hints.append(_hint('dow_init', f'{"/".join(diff)} が違う（EA {"/".join(_fi(ea_row.get(c)) for c in diff)}・'
                                           f'Python {"/".join(_fi(py_row.get(c)) for c in diff)}）。持続型ダウ状態機械は始点から再生する'
                                           'ので、始点が違うと最初の転換イベントまでずれる'))
            explained = True
    hints += _context_hints(t, ctx)
    if not hints:
        hints.append(_hint('engine', 'ここまでの分類に当たらない。EA の判定エンジン部（//@@ENGINE_BEGIN〜END）を直したなら、'
                                     'mt5/engine_check/run.sh で C++ に写した EA と Python を照合する'))
    return _dedup(hints)


def _touch_margin(py, t, d, price):
    """足 t で逆指値 price に届いたか（Python と同じ: 買いは高値＋s/2、売りは安値−s/2）。戻り値: 余裕（価格。正なら届いた）"""
    A = py.arrays
    if d == 1:
        return float(A['H'][t] + py.s_nom / 2 - price)
    return float(price - (A['L'][t] - py.s_nom / 2))


def _touch_hint(py, t, d, price, ctx, lead):
    """約定足の判定の余裕 → スプレッド（すれすれ）か約定判定の移植（余裕がある）か"""
    mg = _touch_margin(py, t, d, float(price))
    pts = mg / ctx.point
    side = 'Ask 高値（高値＋s/2）' if d == 1 else 'Bid 安値（安値−s/2）'
    txt = f'{lead}足 {_ft(py.bars.index[t])} の{side}と逆指値 {float(price):.{_digits(ctx.point) + 2}f} の差は {pts:+.1f} ポイント（正なら届く）。'
    if abs(mg) <= max(py.s_nom, 2 * ctx.point):
        return _hint('spread', txt + 'すれすれなので、スプレッドの扱い（テスターは固定 s_nom か、_info.csv の s_nom）で約定が分かれる')
    if ctx.real:
        return _hint('real_only', txt + '余裕はあるので、実約定側の見送り・発注の失敗・逆指値の置き直しの遅れを確認')
    return _hint('engine', txt + '余裕があるのに約定が分かれた。EA の約定判定（§7.4: 買いは高値＋s/2 ≥ 逆指値、売りは安値−s/2 ≤ 逆指値）を確認')


def trade_hints(m, ea, pyt, ctx):
    """取引の食い違い → ヒントの一覧"""
    py = ctx.py
    hints = []
    e = None if m['ea'] is None else ea.loc[m['ea']]
    p = None if m['py'] is None else pyt.loc[m['py']]
    row = p if p is not None else e
    d = int(row['dir'])
    te = int(row['entry_bar'])
    kinds = m['issues']
    n = len(py.bars)
    if ('PY_ONLY' in kinds or 'EA_ONLY' in kinds) and 1 <= te < n:
        side_in = 'Python' if 'PY_ONLY' in kinds else 'EA'
        bt = py.bars.index[te - 1]
        pr = {(r['dir'], r['pattern']): r for r in _eval_rows_at(py.evals, bt, d)}
        if ctx.ea_eval is not None:
            er = {(r['dir'], r['pattern']): r for r in _eval_rows_at(ctx.ea_eval, bt, d)}
            keys = sorted(set(er) | set(pr), key=lambda k: (k[0] != d, k[1]))
            diff = [(er.get(k), pr.get(k)) for k in keys
                    if er.get(k) is None or pr.get(k) is None or er[k]['code'] != pr[k]['code']]
            if diff:
                x, y = diff[0]
                hints += eval_hints(x, y, te - 1, ctx)
            else:
                armed = [r for r in pr.values() if r['code'] in ('ARMED', 'UPDATE') and r['dir'] == d]
                if armed and not _isnan(armed[0]['price']):
                    diffs = _value_diffs(er.get((d, armed[0]['pattern'])), armed[0])
                    if diffs:
                        hints.append(_value_hint(diffs, ctx))
                    hints.append(_touch_hint(py, te, d, armed[0]['price'], ctx, '直前の足の判定は両側で同じ。約定'))
        else:
            y = next((r for r in pr.values() if r['dir'] == d), None) or next(iter(pr.values()), None)
            if y is not None:
                c = str(y['code'])
                if c == 'T4':
                    hints.append(_hint('chain', 'Python はこの時点で別の建玉を持っていた（T4）。前の取引の食い違いの連鎖'))
                elif c in T_CODES:
                    hints.append(_time_hint(te - 1, ctx, f'Python は直前の足を見送った（{c}）'))
                elif c in ('ARMED', 'UPDATE') and not _isnan(y['price']):
                    hints.append(_touch_hint(py, te, d, y['price'], ctx, 'Python は直前の足で逆指値を置いた。約定'))
                    if side_in == 'Python':
                        hints.append(_hint('engine', 'EA が直前の足で同じ逆指値を置いたかは、EA の評価ログ（--eval）で確かめられる'))
                else:
                    bh = _boundary_hints(c, d, int(y['pattern']), te - 1, None, y, py.diag.get((te - 1, d, int(y['pattern']))), ctx)
                    hints += bh
                    hints.append(_hint('engine', f'Python は直前の足を {c}（{CODE_DESC.get(c, "")}）で見送った。'
                                                 'EA の評価ログ（--eval）を渡すと、EA がなぜ置いたかを並べて見られる'))
        if ctx.real:
            hints.append(_hint('real_only', 'スプレッド防御（3×s_nom 超）・STOPS_LEVEL・FREEZE_LEVEL・発注の失敗で、'
                                            '実約定側だけ見送ることがある（EA のエキスパートログで確認）'))
    if 'SHIFT' in kinds and e is not None and p is not None:
        pb = py.pend_before[int(p['entry_bar'])]
        if ctx.real:
            hints.append(_hint('fill_order', '同じ方向の取引が1本ずれて約定した。実ティックでは足の境目の約定・逆指値の修正の遅れでずれる'))
        elif pb is not None:
            if int(e['entry_bar']) > int(p['entry_bar']):
                hints.append(_touch_hint(py, int(p['entry_bar']), d, pb['price'], ctx, 'EA は1本遅れて約定した。Python の約定'))
            else:
                hints.append(_hint('initial_state', 'EA が1本早く約定した。EA は Python より1本早く逆指値を置いている（評価ログの直前の足を確認）'))
    if 'SL' in kinds or 'SL_EXACT' in kinds:
        if ctx.real:
            hints.append(_hint('real_only', '実約定の初期 SL は NormalizeDouble・STOPS_LEVEL で調整されうる'))
        else:
            hints.append(_hint('window', '初期 SL は約定直前の置き直しの runLow − max(0.2ATR, 3×s_nom) で決まる。'
                                         'ATR・runLow の差（始点・欠損足）か s_nom の違い（_info.csv の s_nom）を確認'))
        if ctx.ea_eval is not None and p is not None and int(p['entry_bar']) >= 1:
            bt = py.bars.index[int(p['entry_bar']) - 1]
            x = next((r for r in _eval_rows_at(ctx.ea_eval, bt, d) if r['code'] in ('ARMED', 'UPDATE')), None)
            y = next((r for r in _eval_rows_at(py.evals, bt, d) if r['code'] in ('ARMED', 'UPDATE')), None)
            diffs = _value_diffs(x, y)
            if diffs:
                hints.append(_value_hint(diffs, ctx))
    if 'EXIT_REASON' in kinds or 'EXIT_TIME' in kinds:
        ra = '' if e is None else str(e['exit_reason'])
        rb = '' if p is None else str(p['exit_reason'])
        if 'END' in (ra, rb):
            hints.append(_hint('end', 'END は EA の停止時（OnDeinit）／Python の最後の足で残りを閉じた行。比べる期間の終わり（--to）をそろえる'))
        if {'WEEKEND', 'GAP_FALLBACK'} & {ra, rb}:
            xb = int(p['exit_bar']) if p is not None else int(row['entry_bar'])
            hints.append(_time_hint(min(max(xb, 0), n - 1), ctx, f'週末・休場決済か休場明けが絡む（EA {ra} / Python {rb}）'))
        if ctx.real:
            hints.append(_hint('fill_order', '実ティックは足の中の順序どおりに約定する（Python は SL 優先、約定足は SL だけ。§10.2）'))
            hints.append(_hint('real_only', 'トレールの修正は new_SL < Bid − stops_level のときだけ通る（§17.7）。FREEZE_LEVEL で拒否されると次の足で再試行'))
        else:
            if p is not None and int(p['exit_bar']) == int(p['entry_bar']):
                hints.append(_hint('fill_order', 'Python は約定足で SL に届いた（約定足では SL だけを判定。§10.2）'))
            if 'TRAIL' in (ra, rb):
                hints.append(_hint('window', 'トレールは BIG 帳簿（深さ12・3000本）の最新の安値・高値と ATR で決まる。帳簿の範囲・足の集合を確認'))
    if 'KEY' in kinds:
        hints.append(_hint('window', 'key（1H の戻り高値・安値の足）が違う。SMALL 帳簿（深さ3・400本）と足の集合を確認'))
    if 0 <= te < n:
        hints += _context_hints(te, ctx)
    if not hints:
        hints.append(_hint('engine', 'ここまでの分類に当たらない。mt5/engine_check/run.sh で EA のエンジン部と Python を照合する'))
    return _dedup(hints)


# ---------------------------------------------------------------- 全体
@dataclass
class ParityResult:
    symbol: str
    base: str
    offset_h: int
    point: float
    real: bool
    config: str
    py: PyRun
    ea_trades: pd.DataFrame
    ea_eval: object
    tcmp: TradeCmp
    ecmp: object
    ctx: Ctx
    t_from: object
    t_to: object
    notes: list = field(default_factory=list)
    paths: dict = field(default_factory=dict)

    @property
    def passed(self):
        return self.tcmp.passed

    @property
    def exact(self):
        if self.tcmp.exact is None:
            return None
        return bool(self.tcmp.exact) and (self.ecmp is None or (self.ecmp.n_match == self.ecmp.n_union
                                                                 and not self.ecmp.field_mismatch))


def _guess_info(trades_path):
    d, b = os.path.split(trades_path)
    for suf in ('_trades.csv', '_real.csv'):
        if b.endswith(suf):
            p = os.path.join(d, b[:-len(suf)] + '_info.csv')
            return p if os.path.exists(p) else None
    return None


def compare_logs(py, ea_trades, ea_eval=None, point=None, real=False, t_from=None, t_to=None, start_aligned=True,
                 start_note='', info=None, symbol=None, notes=None, paths=None):
    """読み込み済みの EA のログ（DataFrame）と Python の結果（PyRun）を比べる"""
    point = point or default_point(py.base)
    tcmp, ea_t = compare_trades(ea_trades, py.trades, py.bars.index, point, real, t_from, t_to)
    ecmp = compare_evals(ea_eval, py.evals, t_from, t_to) if ea_eval is not None else None
    ctx = Ctx(py=py, point=point, real=real, start_aligned=start_aligned, start_note=start_note, info=dict(info or {}),
              ecmp=ecmp, ea_eval=ea_eval)
    return ParityResult(symbol=symbol or py.base, base=py.base, offset_h=py.offset_h, point=point, real=real,
                        config=config_name(py.sw), py=py, ea_trades=ea_t, ea_eval=ea_eval, tcmp=tcmp, ecmp=ecmp,
                        ctx=ctx, t_from=t_from, t_to=t_to, notes=list(notes or []), paths=dict(paths or {}))


def run_parity(bars, trades, symbol, eval_path=None, offset=None, date_from=None, date_to=None, info_path=None,
               use_info=True, point=None, variant=None, extra_closed=None, extra_early=None, real=None, s_nom=None):
    """ファイルを読み、Python を同じ足で回して比べる（CLI の本体）"""
    notes = []
    base = symbol_base(symbol)
    info = {}
    if use_info:
        ip = info_path or _guess_info(trades)
        if info_path and not os.path.exists(info_path):
            raise FileNotFoundError(info_path)
        if ip:
            info = read_info(ip)
            notes.append(f'_info.csv を読んだ: {ip}')
    if info.get('base') and info['base'].upper() != base:
        notes.append(f'注意: _info.csv の base={info["base"]} と --symbol の {base} が違う（--symbol を使う）')
    off = offset
    if off is None:
        off = int(float(info['server_offset_h'])) if info.get('server_offset_h', '') not in ('', None) else 0
    elif info.get('server_offset_h', '') not in ('', None) and int(float(info['server_offset_h'])) != off:
        notes.append(f'注意: --offset {off} と _info.csv の server_offset_h={info["server_offset_h"]} が違う（--offset を使う）')
    if variant:
        sw = fs.config(variant)
    else:
        sw = switches_from_info(info)
    xc = parse_days(extra_closed if extra_closed is not None else info.get('extra_closed', ''))
    xe = parse_days(extra_early if extra_early is not None else info.get('extra_early', ''))
    if xc or xe:
        notes.append(f'追加の暦を Python 側にも足した（休場 {len(xc)} 日・早仕舞い {len(xe)} 日。照合の間だけ strategy.calendar_sets を包む）')
    sn = s_nom
    if sn is None and info.get('s_nom'):
        sn = float(info['s_nom'])
    if base in fs.S_NOM and sn is not None and abs(sn - fs.S_NOM[base]) > 1e-12:
        notes.append(f'注意: EA の s_nom={sn:g} が表の {fs.S_NOM[base]:g} と違う（Python は表の値を使う）')
    if base not in fs.S_NOM:
        if sn is None:
            raise ValueError(f'{base} は SPEC §10.3 の表にない銘柄です。_info.csv（s_nom）か --s-nom を渡してください')
        notes.append(f'{base} は表にない銘柄なので、s_nom={sn:g}（EA と同じ値）を照合の間だけ Python に渡した')

    bars_all = read_bars(bars, off)
    if len(bars_all) == 0:
        raise ValueError(f'{bars}: 足がありません')
    ea_tr, real_detected = read_trades(trades)
    is_real = real_detected if real is None else bool(real)
    ea_ev = read_eval(eval_path) if eval_path else None

    # 始点: EA が最初に読み込んだ足から回す（足番号・持続型状態・約定済み集合を EA とそろえる）
    idx = bars_all.index
    start, aligned, start_note = idx[0], None, ''
    fbt = parse_time(info.get('first_bar_time', '')) if info.get('first_bar_time') else pd.NaT
    if not _isnan(fbt):
        if fbt in idx:
            start, aligned, start_note = fbt, True, f'EA の first_bar_time {_ft(fbt)} から回した'
        elif fbt < idx[0]:
            aligned = False
            start_note = f'足の CSV（{_ft(idx[0])}〜）が EA の first_bar_time {_ft(fbt)} より後から始まる'
        else:
            k = int(idx.searchsorted(fbt))
            start, aligned = idx[min(k, len(idx) - 1)], False
            start_note = f'EA の first_bar_time {_ft(fbt)} が足の CSV にない（{_ft(start)} から回した）'
    elif ea_ev is not None and len(ea_ev):
        fe = ea_ev['bar_time'].min()
        warm = fs.FIX['SLOPE_LB'] + 80
        if fe in idx and int(idx.get_loc(fe)) >= warm:
            start, aligned = idx[int(idx.get_loc(fe)) - warm], True
            start_note = f'_info.csv がないので、評価ログの最初の足 {_ft(fe)} の {warm} 本前（{_ft(start)}）から回した'
        else:
            start_note = '_info.csv がなく、評価ログの最初の足からも始点を決められない（足の CSV の先頭から回した）'
    else:
        start_note = '_info.csv がないので、足の CSV の先頭から回した（EA の _bars.csv なら EA と同じ始点）'
    # 終点: EA が最後に処理した足まで（評価ログの最後の行、なければ END の行）
    ea_last = None
    if ea_ev is not None and len(ea_ev):
        ea_last = ea_ev['bar_time'].max()
    elif not is_real:
        ends = ea_tr[ea_tr['exit_reason'].astype(str) == 'END']['exit_time']
        if len(ends):
            ea_last = ends.max() - HOUR
    used = bars_all[bars_all.index >= start]
    if ea_last is not None and ea_last < used.index[-1]:
        used = used[used.index <= ea_last]
        notes.append(f'足の CSV が EA の最後の足 {_ft(ea_last)} より先まであるので、そこで切った')
    elif ea_last is not None and ea_last > used.index[-1]:
        notes.append(f'注意: 足の CSV（〜{_ft(used.index[-1])}）が EA の最後の足 {_ft(ea_last)} より前で終わる。その先は比べられない')
    py = run_python(used, base, off, sw, xc, xe, sn)
    if is_real:
        notes.append('実約定のログとして比べた（決済の時刻は ±1本、窓開けの SL_gap は SL/TRAIL と同じとみなす。完全一致は出さない）')
    res = compare_logs(py, ea_tr, ea_ev, point=point, real=is_real, t_from=parse_time(date_from) if date_from else None,
                       t_to=parse_time(date_to) if date_to else None, start_aligned=aligned, start_note=start_note,
                       info=info, symbol=symbol, notes=notes,
                       paths=dict(bars=bars, trades=trades, eval=eval_path or '', info=info_path or _guess_info(trades) or ''))
    if res.tcmp.out_of_range:
        res.notes.append(f'注意: 足の範囲外の EA の取引 {res.tcmp.out_of_range} 件は比べていない')
    if ea_ev is not None:
        ph = Counter(ea_ev['phase'])
        res.notes.append('評価ログの phase: ' + '、'.join(f'{k or "（空）"} {v:,}' for k, v in sorted(ph.items())))
    return res


# ---------------------------------------------------------------- 表示
def _pct(x):
    return '∞' if math.isinf(x) else f'{x * 100:+.1f}%'


def _fmt_trade(r, dg):
    if r is None:
        return 'なし'
    s = (f"{_dirname(r['dir'])} 約定 {_ft(r['entry_time'])} @{_ff(r['entry'], dg)}  初期SL {_ff(r['initial_sl'], dg)}  "
         f"→ {_ft(r['exit_time'])} {r['exit_reason']}")
    if not _isnan(r['R']):
        s += f" {float(r['R']):+.2f}R"
    if not _isnan(r['key_time']):
        s += f"  key {_ft(r['key_time'])}"
    if not _isnan(r.get('score')):
        s += f"  スコア {int(r['score'])}"
    return s


def _fmt_eval(r, dg):
    if r is None:
        return '（行なし）'
    code = str(r['code'])
    s = f"{_dirname(r['dir'])}{_patname(r['pattern'])} {code}（{CODE_DESC.get(code, '')}）"
    if not _isnan(r.get('key_time')):
        s += f" key {_ft(r['key_time'])}"
    for col, lab, nd in (('price', '逆指値', dg), ('sl', 'SL', dg), ('r_atr', 'R/ATR', 6), ('depth', 'depth', 6),
                         ('slope80', 'slope80', 6), ('conv', 'conv', 6), ('gap', 'gap', 6), ('rr_cf', 'rr_cf', 2)):
        if not _isnan(r.get(col)):
            s += f' {lab} {float(r[col]):.{nd}f}'
    if not _isnan(r.get('rel')):
        s += f" rel {int(r['rel'])}"
    s += f" T_D1/BIG/SMALL {_fi(r.get('T_D1'))}/{_fi(r.get('T_BIG'))}/{_fi(r.get('T_SMALL'))}"
    if not _isnan(r.get('score')):
        s += f" スコア {int(r['score'])}（{'/'.join(_fi(r.get(k)) for k in ('S1', 'S2', 'S3', 'S4', 'S5', 'S6'))}）"
    return s


def _bar_lines(py, t, dg, before=2, after=0):
    out = []
    for k in range(max(0, t - before), min(len(py.bars), t + after + 1)):
        b = py.bars.iloc[k]
        out.append(f'    {_ft(py.bars.index[k])}  O {b["Open"]:.{dg}f} H {b["High"]:.{dg}f} L {b["Low"]:.{dg}f} '
                   f'C {b["Close"]:.{dg}f}  ATR {py.arrays["atr"][k]:.{dg}f}  （{_rule_desc(py, k)}）')
    return out


def _hint_lines(hints):
    return [f'    {i}. 【{h["label"]}】{h["text"]}' for i, h in enumerate(hints, 1)]


def _split_merged_row(row, side):
    """merge 済みの1行 → 片側の評価行 dict（その側に行がなければ None）"""
    if (side == 'ea' and row['_merge'] == 'left_only') or (side == 'py' and row['_merge'] == 'right_only'):
        return None
    r = {c: row[c] for c in ('bar_time', 'dir', 'pattern')}
    for c in EVAL_COLS:
        if c not in r:
            r[c] = row.get(f'{c}_{side}')
    return r


def first_eval_detail(res):
    """評価ログの最初の食い違い → (表示行, ヒント)"""
    ec, py, dg = res.ecmp, res.py, _digits(res.point) + 2
    if ec is None or ec.first_code is None:
        return [], []
    rows = ec.first_code['rows']
    k = ec.first_code['index']
    row = ec.merged.loc[k]
    ea_r, py_r = _split_merged_row(row, 'ea'), _split_merged_row(row, 'py')
    t = py.bar_of(row['bar_time'])
    lines = [f'【評価ログの最初の食い違い】{_ft(row["bar_time"])}（足番号 t={t}、Python の判定開始から {t - py.first} 本目）']
    for _, rr in rows.iterrows():
        a, b = _split_merged_row(rr, 'ea'), _split_merged_row(rr, 'py')
        mark = '  ' if (a is not None and b is not None and a['code'] == b['code']) else '≠ '
        lines.append(f'  {mark}EA    : {_fmt_eval(a, dg)}')
        lines.append(f'  {mark}Python: {_fmt_eval(b, dg)}')
    dd = py.diag.get((t, int(row['dir']), int(row['pattern'])))
    if dd:
        keys = [('j_peak', '押しの起点'), ('sh', 'SH'), ('l0', 'L0'), ('run_ext', 'runLow'), ('R', 'R')]
        parts = []
        for kk, lab in keys:
            if kk in dd:
                v = dd[kk]
                parts.append(f'{lab} {_ft(py.bars.index[int(v)])}' if kk == 'j_peak' else f'{lab} {float(v):.{dg}f}')
        if parts:
            lines.append('    Python の途中の値: ' + '  '.join(parts))
    if 0 <= t < len(py.bars):
        lines.append('  足:')
        lines += _bar_lines(py, t, dg)
    hints = eval_hints(ea_r, py_r, t, res.ctx) if 0 <= t < len(py.bars) else []
    if hints:
        lines.append('  ヒント（SPEC §17。可能性の高い順）:')
        lines += _hint_lines(hints)
    return lines, hints


def first_trade_detail(res):
    """取引の最初の食い違い → (表示行, ヒント)"""
    tc, py, dg = res.tcmp, res.py, _digits(res.point) + 2
    if not tc.mismatches:
        return [], []
    m = tc.mismatches[0]
    e = None if m['ea'] is None else res.ea_trades.loc[m['ea']]
    p = None if m['py'] is None else py.trades.loc[m['py']]
    lines = [f'【取引の最初の食い違い】{_ft(m["time"])}  ' + '・'.join(ISSUE_LABEL.get(x, x) for x in m['issues'])]
    lines.append(f'    EA    : {_fmt_trade(e, dg)}')
    lines.append(f'    Python: {_fmt_trade(p, dg)}')
    if e is not None and p is not None:
        lines.append(f'    差: 約定 {int(e["entry_bar"]) - int(p["entry_bar"]):+d} 本、初期SL {(float(e["initial_sl"]) - float(p["initial_sl"])) / res.point:+.2f} ポイント、'
                     f'約定価格 {(float(e["entry"]) - float(p["entry"])) / res.point:+.2f} ポイント' if not _isnan(e['entry']) else '')
    opp = [(i, j) for i, j in tc.opposite if i == m['ea'] or j == m['py']]
    if opp:
        i, j = opp[0]
        lines.append(f'    ※ ±1本以内に逆方向の取引がある: EA {_fmt_trade(res.ea_trades.loc[i], dg)} / Python {_fmt_trade(py.trades.loc[j], dg)}')
    row = p if p is not None else e
    te = int(row['entry_bar'])
    if 1 <= te < len(py.bars):
        prev = py.bars.index[te - 1]
        d = int(row['dir'])
        lines.append(f'  直前の足 {_ft(prev)} の判定（ここで逆指値を置いた・置き直した）:')
        er = [r for r in _eval_rows_at(res.ea_eval, prev) if r['dir'] in (d, 0)] if res.ea_eval is not None else None
        pr = [r for r in _eval_rows_at(py.evals, prev) if r['dir'] in (d, 0)]
        if er is None:
            lines.append('    EA    : （評価ログなし。--eval を渡すと並べて表示する）')
        else:
            lines += [f'    EA    : {_fmt_eval(r, dg)}' for r in er] or ['    EA    : （行なし）']
        lines += [f'    Python: {_fmt_eval(r, dg)}' for r in pr] or ['    Python: （行なし）']
        pb = py.pend_before[te]
        if pb is not None:
            mg = _touch_margin(py, te, int(pb['dir']), float(pb['price']))
            lines.append(f'    Python の逆指値 {float(pb["price"]):.{dg}f}（{_dirname(pb["dir"])}）に対する約定足の余裕 {mg / res.point:+.1f} ポイント'
                         '（正なら届いた）')
        lines.append('  足:')
        lines += _bar_lines(py, te, dg, before=1, after=1)
    hints = trade_hints(m, res.ea_trades, py.trades, res.ctx)
    if hints:
        lines.append('  ヒント（SPEC §17。可能性の高い順）:')
        lines += _hint_lines(hints)
    return lines, hints


def format_report(res, max_list=10):
    tc, ec, py = res.tcmp, res.ecmp, res.py
    ok = lambda b: '合格' if b else '不合格'
    lines = ['== FUSION-CORE  MT5 EA と Python 参照実装の照合（SPEC §18） ==']
    lines.append(f'銘柄 {res.symbol}（表の名前 {res.base}、s_nom {py.s_nom:g}、1ポイント {res.point:g}）  '
                 f'サーバー時間のずれ {res.offset_h:+d} 時間  構成 {res.config}')
    lines.append(f'足: {len(py.bars):,} 本（{_ft(py.bars.index[0])}〜{_ft(py.bars.index[-1])}、サーバー時間）  '
                 f'判定開始 {_ft(py.bars.index[py.first]) if py.first < len(py.bars) else "—"}  始点: {res.ctx.start_note or "—"}')
    span = f'{_ft(res.t_from) if res.t_from is not None else "先頭"}〜{_ft(res.t_to) if res.t_to is not None else "最後"}'
    lines.append(f'比べた期間: {span}（サーバー時間）  取引ログ: {"実約定（_real.csv）" if res.real else "仮想ブローカー（_trades.csv）"}'
                 f'  評価ログ: {"あり" if ec is not None else "なし"}')
    for n_ in res.notes:
        lines.append(f'  ・{n_}')
    lines.append('')
    lines.append('【合格基準（SPEC §18）】')
    lines.append(f'  回数の差          EA {tc.n_ea} / Python {tc.n_py}  {_pct(tc.count_diff)}（基準 ±{COUNT_TOL * 100:.0f}% 以内）  … {ok(tc.count_ok)}')
    lines.append(f'  ±1本で方向が一致  {len(tc.pairs)}/{max(tc.n_ea, tc.n_py)} = {tc.dir_rate * 100:.1f}%（基準 {DIR_RATE_MIN * 100:.0f}% 以上。'
                 f'対応がついた件数 ÷ 多い方の回数）  … {ok(tc.dir_ok)}')
    lines.append(f'  初期 SL の差      最大 {tc.sl_max_pts:.2f} ポイント、1ポイント超 {tc.sl_over} 件（基準 {SL_POINTS_MAX:g} ポイント以内）  … {ok(tc.sl_ok)}')
    lines.append(f'  → 判定: {ok(res.passed)}')
    lines.append('【参考】')
    lines.append(f'  決済理由の一致    {tc.exit_match}/{len(tc.pairs)} = {tc.exit_rate * 100:.1f}%')
    if tc.exact is not None:
        lines.append(f'  取引の完全一致（約定・決済の時刻と価格、理由、R、保有本数、key、スコア）: {"はい" if tc.exact else "いいえ"}')
    if tc.issue_count:
        lines.append('  食い違いの内訳: ' + '、'.join(f'{ISSUE_LABEL.get(k, k)} {v}' for k, v in tc.issue_count.most_common()))
    if tc.opposite:
        lines.append(f'  ±1本以内で方向だけ逆の取引: {len(tc.opposite)} 組')
    if ec is not None:
        lines.append(f'  評価ログの理由コードの一致率（診断用）: {ec.n_match:,}/{ec.n_union:,} 行 = {ec.rate * 100:.2f}%'
                     f'（EA {ec.n_ea:,} 行・Python {ec.n_py:,} 行、片方だけの行 EA {ec.only_ea}・Python {ec.only_py}）')
        if ec.duplicates:
            lines.append(f'  注意: 評価ログに同じ足・方向の行が {ec.duplicates} 件重複（後の行を使った）')
        codes = [c for c in CODE_ORDER[:-1] + list(CANDIDATE) + list(T_CODES) if ec.funnel_ea.get(c) or ec.funnel_py.get(c)]
        lines.append('  ファネル（EA / Python）: ' + '  '.join(
            f'{c} {ec.funnel_ea.get(c, 0)}/{ec.funnel_py.get(c, 0)}{"" if ec.funnel_ea.get(c, 0) == ec.funnel_py.get(c, 0) else "≠"}'
            for c in codes))
        if ec.confusion:
            lines.append('  食い違いの多い組（EA→Python）: ' + '、'.join(f'{a}→{b} {v}' for (a, b), v in ec.confusion.most_common(6)))
        if ec.offset_shift:
            lines.append(f'  時刻による見送り（T1/T2/T3/T5）は Python を {ec.offset_shift:+d} 時間ずらすと最もよく合う → '
                         f'--offset {res.offset_h + ec.offset_shift} を試す（EA の InpServerOffsetHours と同じ値にする）')
        if ec.bars_only_ea or ec.bars_only_py:
            ex = (ec.bars_only_ea + ec.bars_only_py)[0]
            lines.append(f'  足の集合が違う: EA だけにある足 {len(ec.bars_only_ea)}・Python だけにある足 {len(ec.bars_only_py)}'
                         f'（例 {_ft(ex)}）。EA の _bars.csv を --bars に渡すとそろう')
        if ec.tstate_rows:
            msg = f'  持続型ダウ状態（T_D1/T_BIG/T_SMALL）が違う行: {ec.tstate_rows:,}（最後 {_ft(ec.tstate_last)}）'
            if res.ctx.start_aligned is not True:
                msg += '。始点がそろっていないなら、--from をこれより後にすると初期値の差を除いて比べられる'
            lines.append(msg)
        if ec.field_mismatch:
            lines.append('  コードが同じ行での値の食い違い: ' + '、'.join(f'{k} {v}' for k, v in ec.field_mismatch.most_common()))
            ff = ec.first_field
            if ff is not None:
                row = ec.merged.loc[ff['index']]
                vals = '、'.join(f'{c} EA {row[c + "_ea"]} / Python {row[c + "_py"]}' for c in ff['fields'][:4])
                lines.append(f'    最初: {_ft(ff["bar_time"])} {_dirname(row["dir"])}{_patname(row["pattern"])} {vals}')
    lines.append('')
    tl, th = first_trade_detail(res)
    el, eh = first_eval_detail(res)
    if not tl and not el:
        lines.append('食い違い: なし')
    lines += tl
    if tl and el:
        lines.append('')
    lines += el
    if len(tc.mismatches) > 1 and max_list > 1:
        lines.append('')
        lines.append(f'【取引の食い違い（先頭 {min(max_list, len(tc.mismatches))} 件／全 {len(tc.mismatches)} 件）】')
        dg = _digits(res.point) + 2
        for m in tc.mismatches[:max_list]:
            e = None if m['ea'] is None else res.ea_trades.loc[m['ea']]
            p = None if m['py'] is None else py.trades.loc[m['py']]
            lines.append(f'  {_ft(m["time"])} {"・".join(ISSUE_LABEL.get(x, x) for x in m["issues"])}')
            lines.append(f'      EA {_fmt_trade(e, dg)}')
            lines.append(f'      Py {_fmt_trade(p, dg)}')
    return '\n'.join(lines)


def result_dict(res):
    """JSON 用の要約"""
    tc, ec = res.tcmp, res.ecmp
    _, th = first_trade_detail(res)
    _, eh = first_eval_detail(res)
    first_t = None
    if tc.mismatches:
        m = tc.mismatches[0]
        first_t = dict(time=_ft(m['time']), issues=m['issues'],
                       ea=None if m['ea'] is None else _rec(res.ea_trades.loc[m['ea']]),
                       python=None if m['py'] is None else _rec(res.py.trades.loc[m['py']]), hints=th)
    first_e = None
    if ec is not None and ec.first_code is not None:
        row = ec.merged.loc[ec.first_code['index']]
        first_e = dict(bar_time=_ft(row['bar_time']), dir=int(row['dir']), pattern=int(row['pattern']),
                       ea_code=None if row['_merge'] == 'left_only' else row['code_ea'],
                       python_code=None if row['_merge'] == 'right_only' else row['code_py'], hints=eh)
    return dict(
        symbol=res.symbol, base=res.base, offset_h=res.offset_h, point=res.point, real=res.real, config=res.config,
        bars=len(res.py.bars), first_bar_time=_ft(res.py.bars.index[0]), start_aligned=res.ctx.start_aligned,
        start_note=res.ctx.start_note, notes=res.notes, passed=res.passed, exact=res.exact,
        trades=dict(n_ea=tc.n_ea, n_py=tc.n_py, count_diff=None if math.isinf(tc.count_diff) else tc.count_diff,
                    count_ok=tc.count_ok, pairs=len(tc.pairs), dir_rate=tc.dir_rate, dir_ok=tc.dir_ok,
                    sl_max_points=tc.sl_max_pts, sl_over=tc.sl_over, sl_ok=tc.sl_ok, exit_rate=tc.exit_rate,
                    exact=tc.exact, issues=dict(tc.issue_count), opposite=len(tc.opposite),
                    out_of_range=tc.out_of_range, first_mismatch=first_t),
        eval=None if ec is None else dict(
            rows_ea=ec.n_ea, rows_py=ec.n_py, rows_union=ec.n_union, code_match=ec.n_match, code_match_rate=ec.rate,
            only_ea=ec.only_ea, only_py=ec.only_py, funnel_ea=dict(ec.funnel_ea), funnel_py=dict(ec.funnel_py),
            field_mismatch=dict(ec.field_mismatch), tstate_rows=ec.tstate_rows,
            confusion={f'{a}->{b}': v for (a, b), v in ec.confusion.items()}, first_mismatch=first_e))


def _rec(r):
    out = {}
    for k, v in dict(r).items():
        if isinstance(v, pd.Timestamp):
            out[k] = _ft(v)
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating, float)):
            out[k] = None if math.isnan(v) else float(v)
        else:
            out[k] = v if not _isnan(v) else None
    return out


# ---------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(
        prog='python -m fusion.mt5_parity',
        description='MT5 EA（FX_Fusion_EA）のログと Python 参照実装（fusion.strategy.run_h1）を SPEC §18 の基準で照合する',
        epilog='例: python -m fusion.mt5_parity --bars FusionEA/EURUSD_bars.csv --trades FusionEA/EURUSD_trades.csv '
               '--eval FusionEA/EURUSD_eval.csv --symbol EURUSD')
    ap.add_argument('--bars', required=True, help='MT5 で書き出した H1 足の CSV（EA の <銘柄>_bars.csv を推奨）')
    ap.add_argument('--trades', required=True, help='EA の <銘柄>_trades.csv（自動売買の <銘柄>_real.csv も可）')
    ap.add_argument('--eval', help='EA の <銘柄>_eval.csv（任意。理由コードを比べる）')
    ap.add_argument('--symbol', required=True, help='銘柄名（EURUSD.a などの接尾辞つき可）')
    ap.add_argument('--offset', type=int, default=None,
                    help='サーバー時間 −（NY+7）［時間］。EA の InpServerOffsetHours（省略時は _info.csv、なければ 0）')
    ap.add_argument('--from', dest='date_from', help='比べる期間の開始（サーバー時間。例 2023-01-01）')
    ap.add_argument('--to', dest='date_to', help='比べる期間の終わり（この時刻より前まで）')
    ap.add_argument('--info', help='<銘柄>_info.csv（省略時は --trades と同じ場所を探す）')
    ap.add_argument('--no-info', action='store_true', help='_info.csv を読まない')
    ap.add_argument('--point', type=float, help='1ポイントの価格幅（省略時は JPY 0.001・XAUUSD 0.01・ほか 0.00001）')
    ap.add_argument('--variant', help='Python 側の構成（strategy.VARIANTS の名前）。省略時は _info.csv の switches/params')
    ap.add_argument('--extra-closed', help='追加の休場日 YYYY.MM.DD;...（省略時は _info.csv の extra_closed）')
    ap.add_argument('--extra-early', help='追加の早仕舞い日 YYYY.MM.DD;...（省略時は _info.csv の extra_early）')
    ap.add_argument('--s-nom', type=float, help='表にない銘柄の名目スプレッド（省略時は _info.csv の s_nom）')
    ap.add_argument('--real', action='store_true', default=None, help='--trades を実約定のログとして扱う（ticket 列があれば自動）')
    ap.add_argument('--strict', action='store_true', help='完全一致（取引と評価ログ）も合格の条件にする（仮想ブローカーのログ向け）')
    ap.add_argument('--list', type=int, default=10, help='取引の食い違いを何件まで並べるか（既定 10）')
    ap.add_argument('--json', help='指標と最初の食い違いを JSON で書く')
    ap.add_argument('--export-python', metavar='DIR', help='Python の結果を EA と同じ形式で DIR に書く')
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        res = run_parity(args.bars, args.trades, args.symbol, eval_path=args.eval, offset=args.offset,
                         date_from=args.date_from, date_to=args.date_to, info_path=args.info, use_info=not args.no_info,
                         point=args.point, variant=args.variant, extra_closed=args.extra_closed,
                         extra_early=args.extra_early, real=args.real, s_nom=args.s_nom)
    except (OSError, ValueError, KeyError) as e:
        print(f'エラー: {e}', file=sys.stderr)
        return 2
    print(format_report(res, max_list=args.list))
    if args.export_python:
        paths = write_python_logs(res.py, args.export_python, tag=res.symbol)
        print(f'\nPython の結果を EA の形式で書いた: {", ".join(paths.values())}')
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(result_dict(res), f, ensure_ascii=False, indent=2, default=str)
    ok = res.passed and (not args.strict or bool(res.exact))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
