"""
データ読み込み・時間足変換

すべての関数は「MT5風サーバー時間」の OHLC DataFrame を返す。
  - 列: Open, High, Low, Close, Volume（index はバーの開始時刻、naive datetime）
  - サーバー時間 = ニューヨーク時間 + 7時間（NYクローズ 17:00 = 00:00）
    → 多くのMT5ブローカー（GMT+2/+3、米国夏時間連動）と同じ足の区切りになり、
      日足は週5本、4時間足は 00/04/08/12/16/20 時に始まる。

対応データ:
  1. backtesting.py 同梱の EURUSD 1時間足（UTC、2017-04〜2018-02、5,000本）
  2. OANDA 1分足（UTC）: github.com/FutureSharks/financial-data の
     pyfinancialdata/data/currencies/oanda/<PAIR>/<YEAR>/*.csv
  3. MT5 から書き出した CSV（サーバー時間のまま、変換しない）
"""
import glob
import importlib.util
import os

import pandas as pd

COLS = ['Open', 'High', 'Low', 'Close', 'Volume']

TF_RULES = {'M15': '15min', 'H1': '1h', 'H4': '4h', 'D1': '1D'}
TF_DELTA = {'M15': pd.Timedelta(minutes=15), 'H1': pd.Timedelta(hours=1),
            'H4': pd.Timedelta(hours=4), 'D1': pd.Timedelta(days=1)}


def utc_to_server(index):
    """UTC の naive DatetimeIndex → サーバー時間（NY + 7h）の naive DatetimeIndex"""
    ny = pd.DatetimeIndex(index).tz_localize('UTC').tz_convert('America/New_York')
    return ny.tz_localize(None) + pd.Timedelta(hours=7)


def drop_weekend(df):
    """サーバー時間の土日に入った足（休場中のわずかなティック）を除く"""
    return df[df.index.dayofweek < 5]


def _finish(df):
    df = df[~df.index.duplicated(keep='first')].sort_index()
    for c in COLS:
        if c not in df.columns:
            df[c] = 0.0
    df = df[COLS].astype(float)
    df.index.name = 'Time'
    return drop_weekend(df)


def resample(df, tf):
    """下位足 → 上位足（左ラベル・左閉区間＝MT5と同じ足の区切り）"""
    out = df.resample(TF_RULES[tf], label='left', closed='left').agg(
        {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'})
    return drop_weekend(out.dropna(subset=['Open']))


def build_mtf(base, base_tf, tfs=('M15', 'H1', 'H4', 'D1')):
    """基準足から各時間足を作る（基準足より下位の足は作れないので除外）"""
    order = ['M15', 'H1', 'H4', 'D1']
    out = {base_tf: base}
    for tf in tfs:
        if order.index(tf) > order.index(base_tf):
            out[tf] = resample(base, tf)
    return out


# ------------------------------------------------------------------
# 1. backtesting.py 同梱データ
# ------------------------------------------------------------------
def backtesting_eurusd_path():
    spec = importlib.util.find_spec('backtesting')
    if spec is None or not spec.submodule_search_locations:
        raise FileNotFoundError('backtesting パッケージが見つかりません（pip install backtesting）')
    return os.path.join(list(spec.submodule_search_locations)[0], 'test', 'EURUSD.csv')


def load_backtesting_eurusd():
    df = pd.read_csv(backtesting_eurusd_path(), index_col=0, parse_dates=True)
    df.index = utc_to_server(df.index)
    return _finish(df)


# ------------------------------------------------------------------
# 2. OANDA 1分足（FutureSharks/financial-data）
# ------------------------------------------------------------------
def load_oanda_m1(pair, src_dir, years=None):
    """pair 例: 'EUR_USD'。src_dir は .../pyfinancialdata/data/currencies/oanda"""
    files = sorted(glob.glob(os.path.join(src_dir, pair, '*', '*.csv')))
    if years:
        files = [f for f in files if int(os.path.basename(os.path.dirname(f))) in years]
    if not files:
        raise FileNotFoundError(f'{src_dir}/{pair} にCSVがありません')
    df = pd.concat([pd.read_csv(f, parse_dates=['time']) for f in files])
    df = df.drop_duplicates('time').set_index('time').sort_index()
    df = df.rename(columns=str.capitalize)
    df.index = utc_to_server(df.index)
    return _finish(df)


def prepare_oanda(pair, src_dir, out_dir, tfs=('M15', 'H1', 'H4', 'D1')):
    """1分足を読み込み、各時間足のCSVを out_dir/<SYMBOL>_<TF>.csv に保存"""
    m1 = load_oanda_m1(pair, src_dir)
    symbol = pair.replace('_', '')
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for tf in tfs:
        r = resample(m1, tf)
        p = os.path.join(out_dir, f'{symbol}_{tf}.csv')
        r.to_csv(p, float_format='%.6f')
        paths[tf] = p
    return paths


def load_prepared(symbol, tf, data_dir):
    p = os.path.join(data_dir, f'{symbol}_{tf}.csv')
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    return _finish(df)


# ------------------------------------------------------------------
# 3. MT5 書き出しCSV
# ------------------------------------------------------------------
def load_mt5_csv(path):
    """MT5「バー」書き出し形式（タブ区切り <DATE> <TIME> <OPEN> ...）と
    一般的なカンマ区切り（Date,Time,... / Time,...）に対応。時刻はサーバー時間のまま。"""
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        head = f.readline()
    sep = '\t' if '\t' in head else (';' if ';' in head and ',' not in head else ',')
    raw = pd.read_csv(path, sep=sep, encoding='utf-8-sig')
    raw.columns = [c.strip().strip('<>').strip().upper() for c in raw.columns]
    if 'DATE' in raw.columns and 'TIME' in raw.columns:
        ts = pd.to_datetime(raw['DATE'].astype(str).str.replace('.', '-', regex=False) + ' ' + raw['TIME'].astype(str))
    else:
        key = next(c for c in raw.columns if c in ('DATE', 'TIME', 'DATETIME', 'GMT TIME', 'TIMESTAMP'))
        ts = pd.to_datetime(raw[key].astype(str).str.replace('.', '-', regex=False))
    vol = 'TICKVOL' if 'TICKVOL' in raw.columns else ('VOLUME' if 'VOLUME' in raw.columns else ('VOL' if 'VOL' in raw.columns else None))
    df = pd.DataFrame({
        'Open': raw['OPEN'].values, 'High': raw['HIGH'].values,
        'Low': raw['LOW'].values, 'Close': raw['CLOSE'].values,
        'Volume': raw[vol].values if vol else 0.0,
    }, index=pd.DatetimeIndex(ts))
    return _finish(df)


def infer_tf(df):
    """足の間隔の最頻値から時間足名を推定"""
    step = pd.Series(df.index[1:] - df.index[:-1]).mode().iloc[0]
    for tf, d in TF_DELTA.items():
        if step == d:
            return tf
    raise ValueError(f'未対応の足間隔: {step}')
