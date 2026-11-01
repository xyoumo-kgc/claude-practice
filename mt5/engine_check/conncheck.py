"""FX_Fusion_EA.mq5 の全体（入力・エンジン部・MT5 接続部）を C++ に写して、g++ で構文と型を確かめる（動かさない）。
  python3 conncheck.py ../FX_Fusion_EA.mq5 conn_check.cpp
  g++ -std=c++17 -fsyntax-only -Wall -Wextra -Wshadow -Wno-unused-parameter -Wno-misleading-indentation conn_check.cpp
MetaEditor のない環境で、接続部の綴り・宣言漏れ・引数の数と型・文字列と数値の混ぜ方を見つけるための道具。
MQL5 の API は conn_shim.h の代用の宣言なので、API の本当の引数の形や MQL5 だけの警告は MetaEditor でしか分からない。
同じ出力を conntest.cpp が CONN_MOCK を定義して取り込み、状態を持つ API の模擬（conn_mock.h）で自動売買のシナリオを動かす。
MQL5 と C++ の違いの写し方:
  ・文字列リテラルは string("...")（MQL5 は "a"+"b" ができる）、色リテラル C'r,g,b' は数値
  ・動的配列 T a[] は MqlArray<T>（engine_check/transpile.py と同じ）
  ・CSymbolCtx * の変数（c, c2, c3, cj, ck）の c.x は c->x
  ・関数は使う前に宣言が要るので、全関数の宣言を先頭に置く
"""
import re
import sys

src = open(sys.argv[1], encoding='utf-8-sig').read()
a = re.search(r'^//@@ENGINE_BEGIN\s*$', src, re.M).start()
b = re.search(r'^//@@ENGINE_END\s*$', src, re.M)
inc = src.index('#include <Trade\\Trade.mqh>')
header = src[inc + len('#include <Trade\\Trade.mqh>'):a]
engine = src[a:b.start()]
conn = src[b.end():]

def arrays(t):
    t = re.sub(r'(const\s+)?\b(\w+)\s*&\s*(\w+)\s*\[\s*\]', lambda m: f"{m.group(1) or ''}MqlArray<{m.group(2)}> &{m.group(3)}", t)
    t = re.sub(r'^(\s*)(\w+)\s+(\w+)\s*\[\s*\]\s*;', r'\1MqlArray<\2> \3;', t, flags=re.M)
    return t

def literals(t):
    t = re.sub(r"C'(\d+),(\d+),(\d+)'", lambda m: f"((color)({m.group(1)} | ({m.group(2)} << 8) | ({m.group(3)} << 16)))", t)
    out = []
    for line in t.split('\n'):
        code, sep, com = line, '', ''
        # 行末コメントの手前だけを変換する（文字列の中の // は考慮）
        i, ins = 0, False
        while i < len(line):
            ch = line[i]
            if ch == '\\' and ins:
                i += 2
                continue
            if ch == '"':
                ins = not ins
            elif not ins and line.startswith('//', i):
                code, com = line[:i], line[i:]
                break
            i += 1
        code = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: f'string({m.group(0)})', code)
        out.append(code + com)
    return '\n'.join(out)

# 入力（input group は消し、input は通常の変数に）
header = re.sub(r'^input\s+group\s+.*$', '', header, flags=re.M)
header = re.sub(r'^input\s+', '', header, flags=re.M)
header = literals(header)
engine = arrays(engine)
conn = conn.replace('CSymbolCtx *g_ctx[];', 'MqlArray<CSymbolCtx*> g_ctx;')
conn = arrays(conn)
conn = re.sub(r'\b(c|c2|c3|cj|ck)\.(?=[A-Za-z_])', r'\1->', conn)
conn = literals(conn)
# 関数の宣言（トップレベルの定義から）
protos = []
for m in re.finditer(r'^([A-Za-z_][\w<>]*(?:\s*\*)?)\s+\*?\s*([A-Za-z_]\w*)\(([^;{}]*)\)\s*\n\s*\{', conn, re.M):
    ret, name, params = m.group(1), m.group(2), m.group(3)
    if ret in ('return', 'else', 'new', 'delete'):
        continue
    star = '*' if re.search(r'\*\s*' + name + r'\(', m.group(0)) else ''
    protos.append(f'{ret} {star}{name}({params});')
out = ['#include "mql5shim.h"', '#include "conn_shim.h"', header, engine,
       '// ---- 接続部の関数の宣言（MQL5 は宣言なしで後ろの関数を呼べる）']
cls = conn.find('class CRealState')
conn_classes_end = conn.find('//+', conn.find('CSymbolCtx::CSymbolCtx(void)'))
out.append(conn[:conn_classes_end])
glob_end = conn.find('//+', conn.find('string      g_offsetNote'))
out.append(conn[conn_classes_end:glob_end])
out.extend(protos)
out.append(conn[glob_end:])
open(sys.argv[2], 'w', encoding='utf-8').write('\n'.join(out))
print('protos', len(protos))
