"""C++ に写した EA エンジンの出力と Python 参照実装の出力を突き合わせる
  python3 compare.py py_prefix mt_prefix"""
import sys
import pandas as pd, numpy as np
py, mt = sys.argv[1], sys.argv[2]
pe = pd.read_csv(py + '_eval.csv', dtype=str, keep_default_na=False)
me = pd.read_csv(mt + '_eval.csv', dtype=str, keep_default_na=False)
OFF = int(sys.argv[3]) if len(sys.argv) > 3 else 0
def unshift(col):
    v = pd.to_datetime(col, format='%Y.%m.%d %H:%M', errors='coerce') - pd.Timedelta(hours=OFF)
    return v.dt.strftime('%Y.%m.%d %H:%M').where(col != '', '')
if OFF:
    for cc in ('bar_time', 'key_time'):
        me[cc] = unshift(me[cc])
print('eval rows  py', len(pe), ' mt', len(me))
k = ['bar_time', 'dir', 'pattern']
pe['n'] = pe.groupby(k).cumcount(); me['n'] = me.groupby(k).cumcount()
m = pe.merge(me, on=k + ['n'], how='outer', suffixes=('_py', '_mt'), indicator=True)
only = m[m['_merge'] != 'both']
print('rows only in one side:', len(only))
if len(only):
    print(only[k + ['code_py', 'code_mt', '_merge']].head(20).to_string())
b = m[m['_merge'] == 'both']
diff = b[b['code_py'] != b['code_mt']]
print('code mismatches:', len(diff))
if len(diff):
    print(diff[k + ['code_py', 'code_mt']].head(30).to_string())
print('funnel py :', pe['code'].value_counts().sort_index().to_dict())
print('funnel mt :', me['code'].value_counts().sort_index().to_dict())
# 候補（ARMED/UPDATE/LOSE）の数値
cand = b[b['code_py'].isin(['ARMED', 'UPDATE', 'LOSE'])]
worst = {}
for a, bcol, tol in (('price_py', 'price_mt', 6e-11), ('sl_py', 'sl_mt', 6e-11), ('R_py', 'R_mt', 6e-11), ('tp1_py', 'tp1_mt', 6e-11),
                     ('rr_cf_py', 'rr_cf_mt', 1e-5), ('r_atr_py', 'r_atr_mt', 1e-5), ('depth_py', 'depth_mt', 1e-5),
                     ('slope80_py', 'slope80_mt', 1e-5), ('conv_py', 'conv_mt', 1e-5)):
    x = pd.to_numeric(cand[a], errors='coerce'); y = pd.to_numeric(cand[bcol], errors='coerce')
    d = (x - y).abs()
    worst[a[:-3]] = (float(d.max()) if len(d) else 0.0, int((d > tol).sum()))
gx = pd.to_numeric(cand['gap_py'], errors='coerce'); gy = pd.to_numeric(cand['gap_mt'], errors='coerce')
worst['gap'] = (float((gx - gy).abs().max()) if len(cand) else 0.0, int(((gx - gy).abs() > 1e-5).sum()) + int((gx.isna() != gy.isna()).sum()))
for col in ('score', 'n_sup', 'sup', 'rel', 'key_time'):
    worst[col] = (None, int((cand[col + '_py'] != cand[col + '_mt']).sum()))
s_mt = cand['S1'] + '/' + cand['S2'] + '/' + cand['S3'] + '/' + cand['S4'] + '/' + cand['S5'] + '/' + cand['S6']
worst['S1-6'] = (None, int((cand['S'] != s_mt).sum()))
print('candidates:', len(cand), ' (max abs diff, count over tol):', worst)
pt = pd.read_csv(py + '_trades.csv', dtype=str); mtt = pd.read_csv(mt + '_trades.csv', dtype=str)
if OFF:
    for cc in ('entry_time', 'exit_time', 'key_time'):
        mtt[cc] = unshift(mtt[cc])
print('trades py', len(pt), ' mt', len(mtt))
n = min(len(pt), len(mtt)); bad = 0
for i in range(n):
    a, c = pt.iloc[i], mtt.iloc[i]
    same = (a.entry_time == c.entry_time and a.dir == c.dir and a.exit_time == c.exit_time and a.exit_reason == c.exit_reason
            and abs(float(a.entry) - float(c.entry)) < 6e-11 and abs(float(a.initial_sl) - float(c.initial_sl)) < 6e-11
            and abs(float(a.R) - float(c.R)) < 6e-9 and a.bars_held == c.bars_held and a.score == c.score
            and abs(float(a.mfe_r) - float(c.mfe_r)) < 6e-5 and abs(float(a.mae_r) - float(c.mae_r)) < 6e-5)
    if not same:
        bad += 1
        if bad <= 10:
            print('TRADE DIFF', i, '\n  py', a.to_dict(), '\n  mt', c.to_dict())
print('trade mismatches:', bad + abs(len(pt) - len(mtt)))
ok = len(only) == 0 and len(diff) == 0 and bad == 0 and len(pt) == len(mtt) and all(v[1] == 0 for v in worst.values())
print('RESULT:', 'MATCH' if ok else 'MISMATCH')
