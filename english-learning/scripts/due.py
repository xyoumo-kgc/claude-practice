#!/usr/bin/env python3
"""間隔反復（ライトナー方式）の補助スクリプト。標準ライブラリのみ。

  python scripts/due.py list [--date YYYY-MM-DD] [--new N]
      復習期限が来た項目を Box の小さい順に表示し、加えて最近学んだ項目を N 件混ぜる。
  python scripts/due.py grade ID ok|ng [ID ok|ng ...] [--date YYYY-MM-DD]
      採点結果を反映して Box と次回復習日を書き換える（ok: Box+1、ng: Box=1）。
  python scripts/due.py add 種別 "英語" "意味" "例文" 出典 [--date YYYY-MM-DD]
      新しい行を追加する（ID は自動採番、Box=1、次回復習=翌日）。
  python scripts/due.py stats
      Box ごとの件数と、間違いログの分類別集計を表示する。
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB = ROOT / "progress" / "vocab-log.md"
MISTAKES = ROOT / "progress" / "mistakes-log.md"
INTERVALS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}  # Box -> 日数
COLS = ["ID", "種別", "英語", "意味", "例文", "学習日", "Box", "次回復習", "出典"]


def parse_date(s):
    return dt.date.fromisoformat(s)


def read_rows():
    """表のデータ行を dict のリストで返す。行番号も保持する。"""
    lines = VOCAB.read_text(encoding="utf-8").splitlines()
    rows = []
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(COLS) or not re.fullmatch(r"\d+", cells[0]):
            continue
        row = dict(zip(COLS, cells))
        row["_line"] = i
        rows.append(row)
    return lines, rows


def fmt_row(row):
    return "| " + " | ".join(row[c] for c in COLS) + " |"


def cmd_list(args):
    today = parse_date(args.date) if args.date else dt.date.today()
    _, rows = read_rows()
    due = [r for r in rows if parse_date(r["次回復習"]) <= today]
    due.sort(key=lambda r: (int(r["Box"]), r["次回復習"]))
    recent = sorted(
        (r for r in rows if r not in due), key=lambda r: r["学習日"], reverse=True
    )[: args.new]
    if not rows:
        print("ログに項目がありません。まず /english-lesson などで学習してください。")
        return
    print(f"## 復習期限の項目 ({len(due)} 件, 基準日 {today})")
    for r in due:
        print(f"- [{r['ID']}] Box{r['Box']} {r['種別']}: {r['英語']} — {r['意味']}  (例: {r['例文']})")
    if recent:
        print(f"\n## 最近学んだ項目（混ぜる用, {len(recent)} 件）")
        for r in recent:
            print(f"- [{r['ID']}] Box{r['Box']} {r['種別']}: {r['英語']} — {r['意味']}  (例: {r['例文']})")


def cmd_grade(args):
    today = parse_date(args.date) if args.date else dt.date.today()
    if len(args.results) % 2 != 0:
        sys.exit("ID と ok|ng をペアで指定してください")
    lines, rows = read_rows()
    by_id = {r["ID"]: r for r in rows}
    for id_, res in zip(args.results[0::2], args.results[1::2]):
        if id_ not in by_id:
            sys.exit(f"ID {id_} が見つかりません")
        if res not in ("ok", "ng"):
            sys.exit(f"結果は ok か ng: {res}")
        r = by_id[id_]
        box = int(r["Box"])
        box = min(box + 1, 5) if res == "ok" else 1
        r["Box"] = str(box)
        r["次回復習"] = (today + dt.timedelta(days=INTERVALS[box])).isoformat()
        lines[r["_line"]] = fmt_row(r)
        print(f"[{id_}] {r['英語']}: {res} -> Box{box}, 次回 {r['次回復習']}")
    VOCAB.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_add(args):
    today = parse_date(args.date) if args.date else dt.date.today()
    lines, rows = read_rows()
    next_id = max((int(r["ID"]) for r in rows), default=0) + 1
    row = {
        "ID": str(next_id),
        "種別": args.kind,
        "英語": args.english.replace("|", "／"),
        "意味": args.meaning.replace("|", "／"),
        "例文": args.example.replace("|", "／"),
        "学習日": today.isoformat(),
        "Box": "1",
        "次回復習": (today + dt.timedelta(days=1)).isoformat(),
        "出典": args.source,
    }
    # 表の最後の行（ヘッダー区切り行を含む）の直後に挿入する
    last = max([r["_line"] for r in rows], default=None)
    if last is None:
        last = max(i for i, l in enumerate(lines) if l.startswith("|"))
    lines.insert(last + 1, fmt_row(row))
    VOCAB.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"追加: [{next_id}] {row['英語']}")


def cmd_stats(_args):
    _, rows = read_rows()
    print(f"## 語彙ログ: {len(rows)} 件")
    for b in range(1, 6):
        n = sum(1 for r in rows if int(r["Box"]) == b)
        print(f"- Box{b}: {n} 件")
    if MISTAKES.exists():
        counts = {}
        for line in MISTAKES.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 5 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
                counts[cells[3]] = counts.get(cells[3], 0) + 1
        print(f"\n## 間違いログ: {sum(counts.values())} 件（分類別、多い順）")
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"- {k}: {v}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list"); s.add_argument("--date"); s.add_argument("--new", type=int, default=5); s.set_defaults(f=cmd_list)
    s = sub.add_parser("grade"); s.add_argument("results", nargs="+"); s.add_argument("--date"); s.set_defaults(f=cmd_grade)
    s = sub.add_parser("add"); s.add_argument("kind"); s.add_argument("english"); s.add_argument("meaning"); s.add_argument("example"); s.add_argument("source"); s.add_argument("--date"); s.set_defaults(f=cmd_add)
    s = sub.add_parser("stats"); s.set_defaults(f=cmd_stats)
    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
