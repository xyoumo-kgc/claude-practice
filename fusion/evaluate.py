"""
実データ検証ハーネス

  python -m fusion.evaluate --data-dir <準備済みCSVのフォルダ> [--symbols EURUSD,GBPUSD,EURJPY,XAUUSD]
                            [--strategies ma_slope,fourp_score,fusion,...] [--json out.json]

- 戦略は全期間で計算し、エントリー時刻で「開発期間(IS)」「検証期間(OOS)」に振り分けて集計する
  （戦略は因果的＝確定済みの足しか見ないので、全期間で計算しても先読みにならない）
- データ準備: fusion/data.py の prepare_oanda()、または MT5 から H1/M15 を書き出した CSV
"""
import argparse
import json
import os

import pandas as pd

from fusion import baselines as bl
from fusion import broker as bk
from fusion import data as fd
from fusion import stats as st

SPREAD = bk.NOMINAL_SPREAD     # 一般的な口座の平均スプレッド（価格単位）

PERIODS = {
    'IS(2013-2017)': ('2013-01-01', '2017-12-31 23:59'),
    'OOS(2018-2020)': ('2018-01-01', '2020-12-31 23:59'),
}


def strategy_registry():
    """戦略名 → f(frames, symbol) -> 取引リスト"""
    from fusion import strategy as fs
    reg = {
        'ma_slope': lambda d, sym: bl.ma_slope(d['H1'], SPREAD[sym]),
        'fourp_score': lambda d, sym: bl.fourp_score(d['H1'], SPREAD[sym], min_score=70),
        'p2': lambda d, sym: fs.run(d, sym, variant='p2'),
    }
    for name in list(fs.VARIANTS) + list(fs.SENSITIVITY):
        reg[name] = (lambda n: (lambda d, sym: fs.run(d, sym, variant=n)))(name)
    return reg


def load_symbol(symbol, data_dir):
    d = {'H1': fd.load_prepared(symbol, 'H1', data_dir)}
    m15 = os.path.join(data_dir, f'{symbol}_M15.csv')
    if os.path.exists(m15):
        d['M15'] = fd.load_prepared(symbol, 'M15', data_dir)
    return d


def split(trades, periods=PERIODS):
    df = pd.DataFrame(trades)
    out = {}
    for name, (a, b) in periods.items():
        if df.empty:
            out[name] = []
            continue
        t = pd.to_datetime(df['entry_time'])
        out[name] = df[(t >= a) & (t <= b)].to_dict('records')
    return out


def run(data_dir, symbols, strategies, periods=PERIODS, verbose=True):
    reg = strategy_registry()
    results = {}
    for sym in symbols:
        d = load_symbol(sym, data_dir)
        for name in strategies:
            trades = reg[name](d, sym)
            parts = split(trades, periods)
            results[(sym, name)] = {'all': trades, **parts}
            if verbose:
                for pname, tr in parts.items():
                    print(st.fmt(st.summarize(tr, f'{sym} {name} {pname}')))
    if verbose:
        print('\n== 銘柄合算')
        for name in strategies:
            for pname in periods:
                pooled = [t for sym in symbols for t in results[(sym, name)][pname]]
                print(st.fmt(st.summarize(pooled, f'ALL {name} {pname}')))
    return results


def prepare_mt5(paths, symbol, out_dir):
    """MT5書き出しCSV（H1、あれば M15 も）を <out_dir>/<SYMBOL>_<TF>.csv にそろえる"""
    os.makedirs(out_dir, exist_ok=True)
    for p in paths:
        df = fd.load_mt5_csv(p)
        tf = fd.infer_tf(df)
        df.to_csv(os.path.join(out_dir, f'{symbol}_{tf}.csv'), float_format='%.6f')
        print(f'{p}: {tf} {len(df)}本 {df.index.min()} 〜 {df.index.max()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--symbols', default='EURUSD,GBPUSD,EURJPY,XAUUSD')
    ap.add_argument('--strategies', default='ma_slope,fourp_score,fusion')
    ap.add_argument('--mt5', nargs='*', help='MT5書き出しCSV（H1 と任意で M15）。--symbols の1銘柄として取り込む')
    ap.add_argument('--periods', default='IS,OOS', help='集計する期間（IS / OOS / ALL）。開発中は IS のみを見る')
    ap.add_argument('--json')
    a = ap.parse_args()
    if a.mt5:
        prepare_mt5(a.mt5, a.symbols.split(',')[0], a.data_dir)
    want = [w.strip().upper() for w in a.periods.split(',')]
    periods = {k: v for k, v in PERIODS.items() if k.split('(')[0] in want}
    if 'ALL' in want:
        periods['ALL'] = ('1900-01-01', '2100-01-01')
    res = run(a.data_dir, a.symbols.split(','), a.strategies.split(','), periods)
    if a.json:
        out = {f'{s}|{n}|{p}': st.summarize(v[p]) for (s, n), v in res.items() for p in periods}
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
