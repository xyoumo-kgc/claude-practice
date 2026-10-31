#!/bin/bash
# FX_Fusion_EA.mq5 の判定エンジン部を C++ に写し、Python 参照実装 fusion/strategy.py と突き合わせる。
# MetaEditor のない環境で「同じ足で同じ判定」を確かめるための道具（EA 本体の動作には関係しない）。
#
#   FUSION_DATA_DIR=<EURUSD_H1.csv などのある場所> bash mt5/engine_check/run.sh [quick]
#
#   ・比べるもの: 足ごと・方向ごとの理由コード（R00〜R16・ARMED・UPDATE・LOSE・T1〜T5）、
#     候補の price/SL/R/TP1/rr_cf/スコア内訳/支え、取引一覧（約定・決済の時刻と価格・理由・R・保有本数）
#   ・EA と同じ流れで動かす: 先頭 W 本を読み込んで仮想で再生 → 以後は1本ずつ Sync（毎時の取り直しと照合）
#   ・期間は FROM〜TO（既定 2013-01-01〜2018-01-01＝開発期間。未接触データには向けないこと）
#   ・必要: g++（C++17）、python3（numpy・pandas）。作業ディレクトリは WORK（既定は一時ディレクトリ）
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
: "${FUSION_DATA_DIR:?FUSION_DATA_DIR を指定してください}"
FROM=${FROM:-2013-01-01}
TO=${TO:-2018-01-01}
WORK=${WORK:-$(mktemp -d)}
MODE=${1:-full}
cd "$WORK" || exit 1
cp "$HERE"/mql5shim.h "$HERE"/harness.cpp "$HERE"/synctest.cpp "$HERE"/caltest.cpp .
python3 "$HERE/transpile.py" "$REPO/mt5/FX_Fusion_EA.mq5" engine_gen.h || exit 1
for p in harness synctest caltest; do
  g++ -O2 -std=c++17 -Wall -Wno-unused-parameter -Wno-misleading-indentation -o $p $p.cpp || exit 1
done
FAIL=0
./caltest > caltest.out || FAIL=1; tail -1 caltest.out
check() {  # tag pyprefix mtprefix [offset]
  r=$(python3 "$HERE/compare.py" "$2" "$3" ${4:-} | grep -E "trades py|RESULT" | tr '\n' ' ')
  echo "$1: $r"
  case "$r" in *"RESULT: MATCH"*) ;; *) FAIL=1 ;; esac
}
pyrun() {  # sym datadir variant prefix
  FUSION_DATA_DIR=$2 python3 "$HERE/pyref.py" $1 bars_$4.csv py_$4 "$FROM" "$TO" $3 > /dev/null || { echo "pyref $4 failed"; FAIL=1; }
}
SYMS=""
for s in EURUSD GBPUSD EURJPY XAUUSD; do [ -f "$FUSION_DATA_DIR/${s}_H1.csv" ] && SYMS="$SYMS $s"; done
[ "$MODE" = quick ] && SYMS=$(echo $SYMS | awk '{print $1}')
for s in $SYMS; do
  pyrun $s "$FUSION_DATA_DIR" fusion $s
  for W in 10000 600; do
    ./harness bars_$s.csv $s $W mt_${s}_$W 300 > /dev/null && check "$s W=$W" py_$s mt_${s}_$W
  done
done
first=$(echo $SYMS | awk '{print $1}')
[ -z "$first" ] && { echo "データがありません"; exit 1; }
SYNC_BARS=bars_$first.csv ./synctest > synctest.out 2>&1 || FAIL=1; tail -1 synctest.out
if [ "$MODE" != quick ]; then
  ./harness bars_$first.csv $first 10000 mt_${first}_full 10000 > /dev/null && check "$first 毎時10000本を取り直す" py_$first mt_${first}_full
  ./harness bars_$first.csv $first 8000 mt_${first}_b 300 "batch=24,noforming" > /dev/null && check "$first 24本ずつ・形成中の足なし" py_$first mt_${first}_b
  for off in 2 -2; do
    ./harness bars_$first.csv $first 10000 mt_${first}_o$off 300 "" $off > /dev/null && check "$first サーバー時間のずれ $off" py_$first mt_${first}_o$off $off
  done
  python3 "$HERE/make_synth.py" bars_$first.csv synth > /dev/null
  for kind in gap jump; do
    pyrun $first synth/$kind fusion ${first}_$kind
    ./harness bars_${first}_$kind.csv $first 5000 mt_${first}_$kind 300 > /dev/null && check "$first 合成:$kind" py_${first}_$kind mt_${first}_$kind
  done
  for v in "F+G3 g3" "F+d1 d1strict" "F+d1soft d1soft" "F+gap gap" "F+clear clear" "F+clear_d1 clear,daily" "F+support support" "F+slnode slnode" "F+p3 p3"; do
    set -- $v
    for s in $SYMS; do
      pyrun $s "$FUSION_DATA_DIR" $1 ${s}_$1
      ./harness bars_${s}_$1.csv $s 3000 mt_${s}_$1 300 "$2" > /dev/null && check "$s $1" py_${s}_$1 mt_${s}_$1
    done
  done
fi
echo "作業ディレクトリ: $WORK"
[ $FAIL = 0 ] && echo "ALL MATCH" || { echo "MISMATCH あり"; exit 1; }
