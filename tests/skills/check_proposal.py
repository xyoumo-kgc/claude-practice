#!/usr/bin/env python3
"""proposal スキルの生成物を検証する（依存パッケージなし）。

- 固定スペックから作ったシーンが examples/sample-room.json と一致すること
  （＝手で作った間取りと同じ結果になること）
- 見積の内訳が寸法・建具数と辻褄が合うこと
- 不正なスペックがきちんと警告されること

    python3 tests/skills/check_proposal.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "proposal", "scripts")
sys.path.insert(0, SCRIPTS)

import make_scene  # noqa: E402
import make_estimate  # noqa: E402

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  OK   {message}")
    else:
        print(f"  NG   {message}")
        failures.append(message)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_scene() -> None:
    print("[シーン生成]")
    spec = load(os.path.join(ROOT, "tests", "fixtures", "spec-sample-room.json"))
    expected = load(os.path.join(ROOT, "examples", "sample-room.json"))
    make_scene.warnings.clear()
    scene = make_scene.build_scene(spec)

    check(scene["format"] == "web-cad" and scene["version"] == 4, "保存形式が web-cad v4")
    check(scene["meta"] == expected["meta"], "提案書情報(meta)が一致")
    check(not make_scene.warnings, f"警告が出ない（{make_scene.warnings}）")

    actual_map = {(o["type"], o["name"]): o for o in scene["objects"]}
    expected_map = {(o["type"], o["name"]): o for o in expected["objects"]}
    check(set(actual_map) == set(expected_map), "オブジェクトの構成が一致")

    diffs = []
    for key in set(actual_map) & set(expected_map):
        a, b = actual_map[key], expected_map[key]
        for field in ("position", "rotation", "scale", "color", "params"):
            x, y = a.get(field), b.get(field)
            if isinstance(x, list):
                if any(abs(p - q) > 1e-4 for p, q in zip(x, y)):
                    diffs.append((key, field, x, y))
            elif x != y:
                diffs.append((key, field, x, y))
    check(not diffs, f"座標・回転・色・寸法が一致（差分 {len(diffs)} 件: {diffs[:3]}）")

    # ドアが壁の中心線上にあること（Web CAD の吸着範囲に入る位置）
    ldk = next(o for o in scene["objects"] if o["name"] == "LDK")
    door = next(o for o in scene["objects"] if o["name"] == "寝室ドア")
    east_wall = ldk["position"][0] + ldk["params"]["width"] / 2 - make_scene.WALL_THICKNESS / 2
    check(abs(door["position"][0] - east_wall) < 1e-6, "境界壁のドアが壁の中心線上にある")

    # 部屋が隙間なく連結していること（attach 指定）
    bedroom = next(o for o in scene["objects"] if o["name"] == "寝室")
    gap = (bedroom["position"][0] - bedroom["params"]["width"] / 2) - (
        ldk["position"][0] + ldk["params"]["width"] / 2
    )
    check(abs(gap) < 1e-6, "attach で指定した部屋が隙間なく接している")


def check_validation() -> None:
    print("[スペックの検証]")
    make_scene.warnings.clear()
    make_scene.build_scene(
        {
            "rooms": [
                {"name": "A", "width": 3000, "depth": 3000},
                {"name": "B", "width": 3000, "depth": 3000, "x": 1000, "z": 0},
            ],
            "openings": [{"type": "door", "room": "A", "side": "n", "offset": 1400}],
            "furniture": [{"type": "bed", "room": "A", "x": 5000, "z": 0}],
        }
    )
    joined = " / ".join(make_scene.warnings)
    check("重なって" in joined, "部屋の重なりを警告する")
    check("はみ出します" in joined, "壁からはみ出す建具を警告する")
    check("の外に出ています" in joined, "部屋の外の家具を警告する")


def check_estimate() -> None:
    print("[見積の下書き]")
    spec = load(os.path.join(ROOT, "tests", "fixtures", "spec-sample-room.json"))
    prices = load(os.path.join(ROOT, ".claude", "skills", "proposal", "reference", "unit-prices.json"))
    items = {i["name"]: i for i in make_estimate.build_items(spec, prices)}

    # LDK 4.5×4.0 + 寝室 3.0×4.0 = 30.0 m2
    check(abs(items["床仕上げ"]["qty"] - 30.0) < 0.01, "床面積が部屋の寸法と一致(30.0 m2)")
    check(items["天井仕上げ"]["qty"] == items["床仕上げ"]["qty"], "天井面積が床面積と一致")
    check(items["ドア（建具）"]["qty"] == 2 and items["窓（建具）"]["qty"] == 3, "建具の数量が一致")

    # 壁面積は開口部の分だけ控除されている
    gross = 2 * (4.5 + 4.0) * 2.4 + 2 * (3.0 + 4.0) * 2.4
    openings = 2 * (0.9 * 2.0) + 3 * (1.2 * 1.0)
    check(abs(items["壁仕上げ"]["qty"] - (gross - openings)) < 0.01, "壁面積から開口部が控除されている")

    total = sum(i["amount"] for i in items.values())
    check(total > 0 and all(i["amount"] >= 0 for i in items.values()), "金額が算出されている")


def main() -> int:
    check_scene()
    check_validation()
    check_estimate()
    print()
    if failures:
        print(f"失敗 {len(failures)} 件")
        return 1
    print("すべて OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
