#!/usr/bin/env python3
"""要件スペック(mm)から見積内訳の下書きを作る。

使い方:
    python make_estimate.py spec.json -o estimate.md
    python make_estimate.py spec.json --prices my-prices.json --csv estimate.csv

単価は reference/unit-prices.json（サンプル値）を既定で使う。
出力はあくまで**下書き**で、現場条件・搬入・既存撤去などは含まれない。
"""
import argparse
import csv
import json
import os

from make_scene import OPENING_SPECS, mm, place_rooms

DEFAULT_PRICES = os.path.join(os.path.dirname(__file__), "..", "reference", "unit-prices.json")
FURNITURE_LABELS = {
    "chair": "イス",
    "table": "テーブル",
    "sofa": "ソファ",
    "bed": "ベッド",
    "shelf": "棚",
}


def yen(value: float) -> str:
    return f"¥{round(value):,}"


def build_items(spec: dict, prices: dict) -> list[dict]:
    rooms = place_rooms(spec.get("rooms", []))
    openings = spec.get("openings", [])

    floor_area = sum(r["width"] * r["depth"] for r in rooms.values())
    ceiling_area = floor_area
    wall_area = sum(2 * (r["width"] + r["depth"]) * r["height"] for r in rooms.values())
    opening_area = sum(
        OPENING_SPECS[o.get("type", "door")]["width"] * OPENING_SPECS[o.get("type", "door")]["height"]
        for o in openings
    )
    wall_area = max(wall_area - opening_area, 0)

    area = prices["area"]
    fixtures = prices["fixtures"]
    furniture_prices = prices["furniture"]
    fees = prices["fees"]

    items = [
        {"name": "床仕上げ", "qty": round(floor_area, 2), "unit": "m2", "price": area["floor"]},
        {"name": "壁仕上げ", "qty": round(wall_area, 2), "unit": "m2", "price": area["wall"]},
        {"name": "天井仕上げ", "qty": round(ceiling_area, 2), "unit": "m2", "price": area["ceiling"]},
    ]

    for kind, label in (("door", "ドア"), ("window", "窓")):
        count = sum(1 for o in openings if o.get("type", "door") == kind)
        if count:
            items.append({"name": f"{label}（建具）", "qty": count, "unit": "箇所", "price": fixtures[kind]})

    for kind, label in FURNITURE_LABELS.items():
        count = sum(1 for f in spec.get("furniture", []) if f.get("type") == kind)
        if count:
            items.append({"name": f"{label}（家具）", "qty": count, "unit": "点", "price": furniture_prices[kind]})

    items.append({"name": "設計・提案費（3D／提案書作成）", "qty": 1, "unit": "式", "price": fees["design"]})

    for item in items:
        item["amount"] = item["qty"] * item["price"]
    return items


def render_markdown(spec: dict, items: list[dict], prices: dict) -> str:
    fees = prices["fees"]
    subtotal = sum(i["amount"] for i in items)
    overhead = subtotal * fees["overhead_rate"]
    taxable = subtotal + overhead
    tax = taxable * fees["tax_rate"]

    meta = spec.get("meta", {})
    lines = [
        "# お見積書（下書き）",
        "",
        f"- 物件名: {meta.get('project', '') or '（未記入）'}",
        f"- お客様名: {(meta.get('customer', '') + ' 様') if meta.get('customer') else '（未記入）'}",
        "",
        "| 項目 | 数量 | 単位 | 単価 | 金額 |",
        "| --- | ---: | :---: | ---: | ---: |",
    ]
    for item in items:
        lines.append(
            f"| {item['name']} | {item['qty']:,} | {item['unit']} | {yen(item['price'])} | {yen(item['amount'])} |"
        )
    lines += [
        f"| **小計** | | | | **{yen(subtotal)}** |",
        f"| 諸経費（{int(fees['overhead_rate'] * 100)}%） | | | | {yen(overhead)} |",
        f"| 消費税（{int(fees['tax_rate'] * 100)}%） | | | | {yen(tax)} |",
        f"| **合計** | | | | **{yen(taxable + tax)}** |",
        "",
        "## 前提",
        "",
        "- 数量は 3D シーンの寸法から自動算出した概算です（開口部分は壁面積から控除）。",
        "- 既存撤去・下地補修・電気設備・搬入費・現場条件による割増は含みません。",
        f"- 単価は `{os.path.basename(prices.get('_source', 'unit-prices.json'))}` の値です。実勢価格に合わせて調整してください。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="要件スペックから見積内訳の下書きを作る")
    parser.add_argument("spec", help="要件スペック JSON")
    parser.add_argument("-o", "--out", default="estimate.md", help="Markdown 出力先(既定: estimate.md)")
    parser.add_argument("--prices", default=DEFAULT_PRICES, help="単価マスタ JSON")
    parser.add_argument("--csv", help="CSV でも書き出す場合の出力先")
    args = parser.parse_args()

    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    with open(args.prices, encoding="utf-8") as f:
        prices = json.load(f)
    prices["_source"] = args.prices

    items = build_items(spec, prices)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render_markdown(spec, items, prices))

    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["項目", "数量", "単位", "単価", "金額"])
            for item in items:
                writer.writerow([item["name"], item["qty"], item["unit"], item["price"], round(item["amount"])])

    total = sum(i["amount"] for i in items)
    print(f"{args.out} を書き出しました（小計 {yen(total)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
