"""fusion/strategy.py を読み込み、評価ごとの理由コード・候補の値・時刻による見送り（T コード）を記録する版を
メモリ上で作って走らせる（元のファイルは変更しない）。EA の評価ログ（<銘柄>_eval.csv）と同じ粒度で書き出す。
  FUSION_DATA_DIR=<dir> python3 pyref.py SYMBOL bars_out.csv out_prefix [start] [end] [variant]
bars_out.csv には、Python が使った足をそのまま書く（C++ 側の入力にする）。"""
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
import numpy as np
import pandas as pd
from fusion import data as fd

F = lambda x: '%.17g' % float(x)
DATA = os.environ.get('FUSION_DATA_DIR')
if not DATA:
    sys.exit('FUSION_DATA_DIR（<SYMBOL>_H1.csv のある場所）を指定してください')
sym, bars_out, out = sys.argv[1], sys.argv[2], sys.argv[3]
start = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
end = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None
variant = sys.argv[6] if len(sys.argv) > 6 else 'fusion'

src = open(os.path.join(REPO, 'fusion', 'strategy.py'), encoding='utf-8').read()
def rep(s, old, new):
    if s.count(old) != 1:
        sys.exit('fusion/strategy.py の形が変わったため記録用の差し込みができません: ' + repr(old[:60]))
    return s.replace(old, new)
src = rep(src, "    def rej(code):\n        funnel[code] = funnel.get(code, 0) + 1\n",
          "    CUR = [0, 0, 0]; LOG = []; ACT = []; TC = []; RUNLOG.append((LOG, ACT, TC))\n\n"
          "    def rej(code):\n        funnel[code] = funnel.get(code, 0) + 1\n        LOG.append((CUR[0], CUR[1], CUR[2], code, None))\n")
src = rep(src, "    def setup(t, d, pattern):\n        \"\"\"足 t の確定時点で方向 d の注文案を作る（SPEC §5〜§9）。不成立なら理由コードを数えて None\"\"\"\n",
          "    def setup(t, d, pattern):\n        CUR[0] = t; CUR[1] = d; CUR[2] = pattern\n")
src = rep(src, "        return dict(dir=d, key=key, price=price, sl=sl, tp1=tp1, meta=meta)\n",
          "        LOG.append((t, d, pattern, 'OK', dict(key_idx=int(j_sh), price=price, sl=sl, tp1=tp1, R=R, score=score, rr_cf=rr_cf,"
          " n_sup=len(types), sup='+'.join(sorted(types)), r_atr=R / a_t, depth=depth, slope=slope, conv=conv,"
          " gap=(None if np.isnan(gap) else gap), rel=rel, s=(s1, s2, s3, s4, s5, s6))))\n"
          "        return dict(dir=d, key=key, price=price, sl=sl, tp1=tp1, meta=meta)\n")
src = rep(src, "        if flat[t]:\n            pend = None; market = None\n            continue\n",
          "        if flat[t]:\n            TC.append((t, 'FLAT'))\n            pend = None; market = None\n            continue\n")
src = rep(src, "        if br.open or market is not None:\n            continue\n        if no_new[t] or rollover[t]:\n            pend = None\n            continue\n",
          "        if br.open or market is not None:\n            TC.append((t, 'T4'))\n            continue\n"
          "        if no_new[t] or rollover[t]:\n            TC.append((t, 'T2' if no_new[t] else 'T3'))\n            pend = None\n            continue\n")
src = rep(src, "            funnel['ARMED'] = funnel.get('ARMED', 0) + 1\n",
          "            funnel['ARMED'] = funnel.get('ARMED', 0) + 1\n            ACT.append((t, 'ARMED', best['dir'], best['meta']['pattern']))\n")
src = rep(src, "        else:                                                  # 同じセットアップ: 価格・SL を置き直す\n",
          "        else:                                                  # 同じセットアップ: 価格・SL を置き直す\n            ACT.append((t, 'UPDATE', best['dir'], best['meta']['pattern']))\n")
mod = types.ModuleType('fs_patched'); mod.__dict__['RUNLOG'] = []
exec(compile(src, 'strategy_patched.py', 'exec'), mod.__dict__)

h1 = fd.load_prepared(sym, 'H1', DATA)
if start: h1 = h1[h1.index >= start]
if end: h1 = h1[h1.index < end]
with open(bars_out, 'w') as f:
    f.write('Time,Open,High,Low,Close,Volume\n')
    for ts, r in zip(h1.index, h1[['Open', 'High', 'Low', 'Close', 'Volume']].to_numpy()):
        f.write('%s,%r,%r,%r,%r,%r\n' % (ts.strftime('%Y-%m-%d %H:%M:%S'), *[float(x) for x in r]))
trades, funnel = mod.run_h1(h1, sym, mod.config(variant))
LOG, ACT, TC = mod.RUNLOG[-1]
idx = h1.index
act = {(t, d, p): k for t, k, d, p in ACT}
closed, early = mod.calendar_sets(sym, range(idx[0].year, idx[-1].year + 2))
fmt = lambda ts: ts.strftime('%Y.%m.%d %H:%M')
rows = []
for t, d, p, code, info in LOG:
    if code == 'OK':
        code = act.get((t, d, p), 'LOSE')
    rows.append((t, 1, fmt(idx[t]), d, p, code, info))
for t, k in TC:
    if k == 'FLAT':
        k = 'T1' if idx[t].date() in closed else 'T5'
    rows.append((t, 0, fmt(idx[t]), 0, 0, k, None))
rows.sort(key=lambda r: (r[0], r[1]))
with open(out + '_eval.csv', 'w') as f:
    f.write('bar_time,dir,pattern,code,key_time,price,sl,R,score,rr_cf,n_sup,sup,r_atr,depth,slope80,conv,gap,rel,tp1,S\n')
    for t, _, bt, d, p, code, info in rows:
        if info is None:
            f.write(f'{bt},{d},{p},{code},,,,,,,,,,,,,,,,\n')
        else:
            g = '' if info['gap'] is None else F(info['gap'])
            f.write(f"{bt},{d},{p},{code},{fmt(idx[info['key_idx']])},{F(info['price'])},{F(info['sl'])},{F(info['R'])},{info['score']},"
                    f"{F(info['rr_cf'])},{info['n_sup']},{info['sup']},{F(info['r_atr'])},{F(info['depth'])},{F(info['slope'])},"
                    f"{F(info['conv'])},{g},{info['rel']},{F(info['tp1'])},{'/'.join(map(str, info['s']))}\n")
with open(out + '_trades.csv', 'w') as f:
    f.write('entry_time,dir,entry,initial_sl,exit_time,exit_reason,R,bars_held,score,pattern,mfe_r,mae_r\n')
    for tr in trades:
        f.write(f"{fmt(tr['entry_time'])},{tr['direction']},{F(tr['entry'])},{F(tr['initial_sl'])},{fmt(tr['exit_time'])},{tr['exit_reason']},"
                f"{F(tr['pnl_r'])},{tr['bars_held']},{tr['m_score']},{tr['m_pattern']},{F(tr['mfe_r'])},{F(tr['mae_r'])}\n")
print('bars', len(h1), 'trades', len(trades), sorted(funnel.items()))
