"""mt5/FX_Fusion_EA.mq5 の判定エンジン部（行頭の //@@ENGINE_BEGIN 〜 //@@ENGINE_END）を C++ に写す。
書き換えは配列の宣言（double a[]; → MqlArray<double> a;）と配列引数（const double &a[] → const MqlArray<double> &a）だけ。
  python3 transpile.py ../FX_Fusion_EA.mq5 engine_gen.h"""
import re
import sys

src = open(sys.argv[1], encoding='utf-8').read()
a = re.search(r'^//@@ENGINE_BEGIN\s*$', src, re.M).start()
b = re.search(r'^//@@ENGINE_END\s*$', src, re.M).start()
eng = src[a:b]
eng = re.sub(r'(const\s+)?\b(\w+)\s*&\s*(\w+)\s*\[\s*\]', lambda m: f"{m.group(1) or ''}MqlArray<{m.group(2)}> &{m.group(3)}", eng)
eng = re.sub(r'^(\s*)(\w+)\s+(\w+)\s*\[\s*\]\s*;', r'\1MqlArray<\2> \3;', eng, flags=re.M)
open(sys.argv[2], 'w', encoding='utf-8').write('#pragma once\n#include "mql5shim.h"\n' + eng)
print('engine lines:', eng.count('\n'))
