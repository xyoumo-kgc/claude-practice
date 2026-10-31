"""成績集計（R単位）"""
import math

import numpy as np
import pandas as pd


def summarize(trades, label=''):
    """trades: trade_record() の辞書リスト or DataFrame"""
    df = pd.DataFrame(trades)
    if df.empty:
        return {'label': label, 'trades': 0}
    r = df['pnl_r'].astype(float)
    wins, losses = r[r > 0], r[r <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    eq = r.cumsum()
    dd = (eq - eq.cummax().clip(lower=0)).min()
    # 連敗
    streak = worst = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)
    sd = r.std(ddof=1) if len(r) > 1 else float('nan')
    return {
        'label': label,
        'trades': int(len(r)),
        'win_rate': float((r > 0).mean()),
        'total_r': float(r.sum()),
        'avg_r': float(r.mean()),
        'pf': float(gross_win / gross_loss) if gross_loss > 0 else float('inf'),
        'avg_win_r': float(wins.mean()) if len(wins) else 0.0,
        'avg_loss_r': float(losses.mean()) if len(losses) else 0.0,
        'max_dd_r': float(dd),
        'max_losing_streak': int(worst),
        't_stat': float(r.mean() / sd * math.sqrt(len(r))) if sd and sd > 0 else float('nan'),
        'long_short': f"{int((df['direction'] == 1).sum())}/{int((df['direction'] == -1).sum())}" if 'direction' in df else '',
    }


def by_period(trades, freq='Y'):
    df = pd.DataFrame(trades)
    if df.empty:
        return pd.DataFrame()
    t = pd.to_datetime(df['entry_time'])
    key = t.dt.year if freq == 'Y' else t.dt.to_period('M').astype(str)
    g = df.groupby(key)['pnl_r']
    return pd.DataFrame({'trades': g.size(), 'total_r': g.sum(), 'win_rate': g.apply(lambda x: (x > 0).mean())})


def fmt(s):
    if not s or s.get('trades', 0) == 0:
        return f"{s.get('label', ''):<28} trades=0"
    pf = '∞' if s['pf'] == float('inf') else f"{s['pf']:.2f}"
    return (f"{s['label']:<28} n={s['trades']:>4}  win={s['win_rate']*100:5.1f}%  total={s['total_r']:+7.1f}R  "
            f"avg={s['avg_r']:+.3f}R  PF={pf:>5}  DD={s['max_dd_r']:+.1f}R  t={s['t_stat']:+.2f}  L/S={s['long_short']}")
