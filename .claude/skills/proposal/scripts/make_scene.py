#!/usr/bin/env python3
"""要件スペック(mm)から Web CAD のシーン JSON を生成する。

使い方:
    python make_scene.py spec.json -o scene.json

スペックの形式は reference/spec-template.json を参照。
座標・寸法はすべて mm で書き、出力(Web CAD の保存形式)では m に変換される。
"""
import argparse
import json
import math
import sys

# src/objects.ts の定数に合わせる
WALL_THICKNESS = 0.12
FLOOR_THICKNESS = 0.05
DEFAULT_HEIGHT_MM = 2400
OPENING_SPECS = {
    "door": {"width": 0.9, "height": 2.0, "bottom": 0.0},
    "window": {"width": 1.2, "height": 1.0, "bottom": 0.9},
}
DEFAULT_COLORS = {
    "room": "#c9a97a",
    "door": "#8a6a48",
    "window": "#f0f2f4",
    "chair": "#b5835a",
    "table": "#8a6a48",
    "sofa": "#6b8cae",
    "bed": "#9a7b5c",
    "shelf": "#a8845f",
}
FURNITURE_TYPES = ("chair", "table", "sofa", "bed", "shelf")
SIDES = ("n", "s", "e", "w")

warnings: list[str] = []


def warn(message: str) -> None:
    warnings.append(message)


def mm(value) -> float:
    """mm を m に変換する。"""
    return round(float(value) / 1000.0, 4)


def place_rooms(specs: list[dict]) -> dict[str, dict]:
    """部屋の中心座標(m)を決める。attach 指定は隣の部屋にぴったり接するように配置する。"""
    rooms: dict[str, dict] = {}
    pending = list(specs)
    guard = len(pending) + 1

    while pending and guard > 0:
        guard -= 1
        rest = []
        for spec in pending:
            name = spec["name"]
            width, depth = mm(spec["width"]), mm(spec["depth"])
            height = mm(spec.get("height", DEFAULT_HEIGHT_MM))
            attach = spec.get("attach")

            if attach is None:
                cx, cz = mm(spec.get("x", 0)), mm(spec.get("z", 0))
            else:
                base = rooms.get(attach["to"])
                if base is None:
                    rest.append(spec)  # 接続先がまだ配置されていない
                    continue
                cx, cz = attach_position(base, width, depth, attach)

            rooms[name] = {
                "name": name,
                "cx": cx,
                "cz": cz,
                "width": width,
                "depth": depth,
                "height": height,
                "color": spec.get("color", DEFAULT_COLORS["room"]),
            }
        if len(rest) == len(pending):
            raise SystemExit(f"attach の接続先が見つかりません: {[s['name'] for s in rest]}")
        pending = rest

    return rooms


def attach_position(base: dict, width: float, depth: float, attach: dict) -> tuple[float, float]:
    """base の指定した辺に接する位置を返す。shift(mm) でずらせる。"""
    side = attach.get("side", "e")
    if side not in SIDES:
        raise SystemExit(f"attach.side は {SIDES} のいずれかです: {side}")
    shift = mm(attach.get("shift", 0))

    if side == "e":
        return base["cx"] + base["width"] / 2 + width / 2, base["cz"] + shift
    if side == "w":
        return base["cx"] - base["width"] / 2 - width / 2, base["cz"] + shift
    if side == "s":
        return base["cx"] + shift, base["cz"] + base["depth"] / 2 + depth / 2
    return base["cx"] + shift, base["cz"] - base["depth"] / 2 - depth / 2


def check_overlap(rooms: dict[str, dict]) -> None:
    """部屋同士が重なっていないか確認する(辺が接しているのは正常)。"""
    items = list(rooms.values())
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            dx = abs(a["cx"] - b["cx"]) - (a["width"] + b["width"]) / 2
            dz = abs(a["cz"] - b["cz"]) - (a["depth"] + b["depth"]) / 2
            if dx < -0.001 and dz < -0.001:
                warn(f"部屋が重なっています: {a['name']} と {b['name']}")


def wall_length(room: dict, side: str) -> float:
    """壁の有効長(開口部を置ける範囲)。src/objects.ts の buildWall と同じ定義。"""
    if side in ("n", "s"):
        return room["width"]
    return room["depth"] - WALL_THICKNESS * 2


def opening_object(spec: dict, rooms: dict[str, dict], index: int) -> dict:
    """ドア・窓を壁の中心線上に配置する(Web CAD 側の吸着範囲に入る位置)。"""
    kind = spec.get("type", "door")
    if kind not in OPENING_SPECS:
        raise SystemExit(f"建具の type は door / window です: {kind}")
    room = rooms.get(spec["room"])
    if room is None:
        raise SystemExit(f"建具の room が見つかりません: {spec['room']}")
    side = spec.get("side")
    if side not in SIDES:
        raise SystemExit(f"建具の side は {SIDES} のいずれかです: {side}")

    offset = mm(spec.get("offset", 0))
    half = OPENING_SPECS[kind]["width"] / 2
    limit = wall_length(room, side) / 2
    if abs(offset) + half > limit + 0.001:
        warn(
            f"{spec.get('name', kind)}: offset が壁からはみ出します"
            f"（{room['name']} の {side} 壁は ±{int((limit - half) * 1000)}mm まで）"
        )

    t = WALL_THICKNESS
    if side == "s":
        x, z, rot = room["cx"] + offset, room["cz"] + room["depth"] / 2 - t / 2, 0.0
    elif side == "n":
        x, z, rot = room["cx"] + offset, room["cz"] - room["depth"] / 2 + t / 2, 0.0
    elif side == "e":
        x, z, rot = room["cx"] + room["width"] / 2 - t / 2, room["cz"] + offset, math.pi / 2
    else:
        x, z, rot = room["cx"] - room["width"] / 2 + t / 2, room["cz"] + offset, math.pi / 2

    label = "ドア" if kind == "door" else "窓"
    return {
        "type": kind,
        "name": spec.get("name", f"{label} {index}"),
        "position": [round(x, 4), FLOOR_THICKNESS, round(z, 4)],
        "rotation": [0, round(rot, 4), 0],
        "scale": [1, 1, 1],
        "color": spec.get("color", DEFAULT_COLORS[kind]),
    }


def furniture_object(spec: dict, rooms: dict[str, dict], index: int) -> dict:
    kind = spec.get("type")
    if kind not in FURNITURE_TYPES:
        raise SystemExit(f"家具の type は {FURNITURE_TYPES} のいずれかです: {kind}")
    room = rooms.get(spec["room"])
    if room is None:
        raise SystemExit(f"家具の room が見つかりません: {spec['room']}")

    # 家具の x/z は部屋の中心からの相対位置(mm)
    x = room["cx"] + mm(spec.get("x", 0))
    z = room["cz"] + mm(spec.get("z", 0))
    if abs(mm(spec.get("x", 0))) > room["width"] / 2 or abs(mm(spec.get("z", 0))) > room["depth"] / 2:
        warn(f"{spec.get('name', kind)}: {room['name']} の外に出ています")

    return {
        "type": kind,
        "name": spec.get("name", f"{kind} {index}"),
        "position": [round(x, 4), FLOOR_THICKNESS, round(z, 4)],
        "rotation": [0, round(math.radians(float(spec.get("rotation", 0))), 4), 0],
        "scale": [1, 1, 1],
        "color": spec.get("color", DEFAULT_COLORS[kind]),
    }


def default_views(rooms: dict[str, dict]) -> list[dict]:
    """全体パースと平面図のアングルを自動で作る(提案書 PDF のページになる)。"""
    xs = [r["cx"] for r in rooms.values()]
    zs = [r["cz"] for r in rooms.values()]
    cx = (min(xs) + max(xs)) / 2
    cz = (min(zs) + max(zs)) / 2
    span = max(
        max(r["cx"] + r["width"] / 2 for r in rooms.values()) - min(r["cx"] - r["width"] / 2 for r in rooms.values()),
        max(r["cz"] + r["depth"] / 2 for r in rooms.values()) - min(r["cz"] - r["depth"] / 2 for r in rooms.values()),
    )
    return [
        {
            "name": "全体パース",
            "mode": "persp",
            "position": [round(cx + span, 3), round(span * 0.8, 3), round(cz + span * 1.1, 3)],
            "target": [round(cx, 3), 0.8, round(cz, 3)],
        },
        {
            "name": "平面図",
            "mode": "plan",
            "position": [round(cx, 3), 30, round(cz, 3)],
            "target": [round(cx, 3), 0, round(cz, 3)],
            "zoom": round(max(6.0 / max(span, 1.0), 0.3), 2),
        },
    ]


def build_scene(spec: dict) -> dict:
    room_specs = spec.get("rooms", [])
    if not room_specs:
        raise SystemExit("rooms が空です。最低 1 部屋は必要です。")

    rooms = place_rooms(room_specs)
    check_overlap(rooms)

    objects = [
        {
            "type": "room",
            "name": r["name"],
            "position": [round(r["cx"], 4), 0, round(r["cz"], 4)],
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1],
            "color": r["color"],
            "params": {"width": r["width"], "depth": r["depth"], "height": r["height"]},
        }
        for r in rooms.values()
    ]
    for i, opening in enumerate(spec.get("openings", []), start=1):
        objects.append(opening_object(opening, rooms, i))
    for i, item in enumerate(spec.get("furniture", []), start=1):
        objects.append(furniture_object(item, rooms, i))

    return {
        "format": "web-cad",
        "version": 4,
        "objects": objects,
        "views": spec.get("views") or default_views(rooms),
        "meta": {
            "project": spec.get("meta", {}).get("project", ""),
            "customer": spec.get("meta", {}).get("customer", ""),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="要件スペック(mm)から Web CAD シーン JSON を生成する")
    parser.add_argument("spec", help="要件スペック JSON")
    parser.add_argument("-o", "--out", default="scene.json", help="出力先(既定: scene.json)")
    args = parser.parse_args()

    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)

    scene = build_scene(spec)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)
        f.write("\n")

    rooms = sum(1 for o in scene["objects"] if o["type"] == "room")
    print(f"{args.out} を書き出しました（部屋 {rooms} / オブジェクト {len(scene['objects'])}）")
    for message in warnings:
        print(f"  [警告] {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
