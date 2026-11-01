"""照合用の合成データ（実データでは起きにくい経路を通す）
  python3 make_synth.py bars.csv outdir
  outdir/gap/<SYM>_H1.csv  … 平日に13時間の穴を空ける（休場明けフォールバック GAP_FALLBACK）
  outdir/jump/<SYM>_H1.csv … 4% の足の始値を飛ばす（窓開けの約定・SL_gap）"""
import os
import sys

import numpy as np
import pandas as pd

src, outdir = sys.argv[1], sys.argv[2]
sym = os.path.basename(src).replace('bars_', '').replace('.csv', '')
df = pd.read_csv(src, parse_dates=['Time'])
wk = df['Time'].dt.isocalendar().week.astype(int)
dow, hr = df['Time'].dt.dayofweek, df['Time'].dt.hour
drop = ((dow == 2) & (wk % 3 == 0) & (hr >= 3) & (hr < 16)) | ((dow == 1) & (wk % 5 == 0) & (hr >= 10) & (hr < 23))
os.makedirs(os.path.join(outdir, 'gap'), exist_ok=True)
g = df[~drop].copy()
g['Time'] = g['Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
g.to_csv(os.path.join(outdir, 'gap', f'{sym}_H1.csv'), index=False)
rng = np.random.default_rng(7)
m = rng.random(len(df)) < 0.04
step = float(np.median(np.abs(np.diff(df['Close'].to_numpy()))))
jump = rng.choice([-1, 1], len(df)) * rng.uniform(1.0, 4.0, len(df)) * 8 * step
j = df.copy()
o = j['Open'].to_numpy().copy()
o[m] = o[m] + jump[m]
j['Open'] = o
j['High'] = np.maximum(j['High'], j['Open'])
j['Low'] = np.minimum(j['Low'], j['Open'])
os.makedirs(os.path.join(outdir, 'jump'), exist_ok=True)
j['Time'] = j['Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
j.to_csv(os.path.join(outdir, 'jump', f'{sym}_H1.csv'), index=False, float_format='%.6f')
print(sym, 'gap: dropped', int(drop.sum()), 'bars / jump:', int(m.sum()), 'bars')
