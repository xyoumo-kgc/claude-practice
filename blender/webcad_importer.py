"""Web CAD → Blender インポーター

Web CAD の「保存」で書き出した JSON を読み込み、Blender 上で編集できる
パース(透視図)用のシーンを組み立てる。

- 部屋: 床・壁・天井(非表示)を持つ Empty。サイドバー「Web CAD」タブで
  幅・奥行・壁高を mm で変更して「再構築」できる
- ドア・窓: 子にカッターを持ち、壁の Boolean モディファイアで開口部を開ける。
  Blender 上でドア・窓を動かすと壁の穴も追従する
- 家具: 部品を 1 メッシュにまとめたオブジェクト(マテリアルは個別)
- 保存アングル: カメラとして作成(平面図アングルは平行投影)

使い方:
  1. 編集 > プリファレンス > アドオン > ディスクからインストール で本ファイルを選ぶ
  2. ファイル > インポート > Web CAD (.json)
  コマンドライン:
  blender --background --python webcad_importer.py -- 入力.json 出力.blend [レンダー.png]
"""

bl_info = {
    "name": "Web CAD Importer",
    "author": "Web CAD",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "ファイル > インポート > Web CAD (.json) / 3Dビュー サイドバー > Web CAD",
    "description": "Web CAD の間取り(JSON)を読み込み、編集できるパース用シーンを作成します",
    "category": "Import-Export",
}

import json
import math
import sys

import bpy  # bpy を先に読み込む(pip 版 bpy では bmesh が bpy の後でないと使えない)
import bmesh
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Matrix, Vector

WALL_T = 0.12
FLOOR_T = 0.05
# 開口部の寸法(幅, 高さ, 床からの高さ)。Web CAD の OPENING_SPECS と同じ値
OPENING_SPECS = {"door": (0.9, 2.0, 0.0), "window": (1.2, 1.0, 0.9)}
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
WALL_COLOR = "#d8d5cd"
CUTTER_COLLECTION = "開口部カッター"

# Web CAD(Y が上、Z が手前)→ Blender(Z が上、Y が奥)の座標変換
_C = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))


def to_bl_location(p):
    return Vector((p[0], -p[2], p[1]))


def to_bl_rotation(r):
    # three.js の 'XYZ' 順は Blender の 'ZYX' 順と同じ行列になる
    rot = Euler((r[0], r[1], r[2]), "ZYX").to_matrix()
    return (_C @ rot @ _C.transposed()).to_euler("XYZ")


def to_bl_scale(s):
    return (s[0], s[2], s[1])


# ---------------------------------------------------------------- マテリアル


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_rgba(hex_color):
    h = hex_color.lstrip("#")
    return tuple(_srgb_to_linear(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4)) + (1.0,)


def _set_input(node, names, value):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return


def make_material(name, hex_color, roughness=0.6, metallic=0.0, glass=False):
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass
    rgba = hex_to_rgba(hex_color)
    mat.diffuse_color = rgba  # ソリッド表示用
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        _set_input(bsdf, ["Base Color"], rgba)
        _set_input(bsdf, ["Roughness"], roughness)
        _set_input(bsdf, ["Metallic"], metallic)
        if glass:
            _set_input(bsdf, ["Transmission Weight", "Transmission"], 1.0)
            _set_input(bsdf, ["IOR"], 1.45)
    if glass:
        mat.diffuse_color = (rgba[0], rgba[1], rgba[2], 0.3)
    return mat


# ------------------------------------------------------------ メッシュ組み立て


class MeshBuilder:
    """Web CAD の座標系で直方体パーツを積み上げ、1 つのメッシュにする"""

    def __init__(self):
        self.bm = bmesh.new()
        self.materials = []

    def _material_index(self, mat):
        if mat not in self.materials:
            self.materials.append(mat)
        return self.materials.index(mat)

    def _assign(self, verts, mat):
        if mat is None:  # 開口部カッターなどマテリアル不要の部品
            return
        index = self._material_index(mat)
        for face in {f for v in verts for f in v.link_faces}:
            face.material_index = index

    def box(self, mat, w, h, d, x, y, z):
        """幅 w・高さ h・奥行 d の直方体を中心 (x, y, z) に追加する(Web CAD 座標)"""
        verts = bmesh.ops.create_cube(self.bm, size=1.0)["verts"]
        bmesh.ops.scale(self.bm, vec=(w, d, h), verts=verts)
        bmesh.ops.translate(self.bm, vec=(x, -z, y), verts=verts)
        self._assign(verts, mat)

    def uv_sphere(self, mat, radius):
        verts = bmesh.ops.create_uvsphere(self.bm, u_segments=32, v_segments=16, radius=radius)["verts"]
        self._assign(verts, mat)

    def cone(self, mat, r1, r2, depth):
        verts = bmesh.ops.create_cone(
            self.bm, cap_ends=True, segments=32, radius1=r1, radius2=r2, depth=depth
        )["verts"]
        self._assign(verts, mat)

    def torus(self, mat, major, minor, seg_major=48, seg_minor=16):
        rings = []
        for i in range(seg_major):
            a = 2 * math.pi * i / seg_major
            ring = []
            for j in range(seg_minor):
                b = 2 * math.pi * j / seg_minor
                r = major + minor * math.cos(b)
                ring.append(self.bm.verts.new((r * math.cos(a), r * math.sin(a), minor * math.sin(b))))
            rings.append(ring)
        for i in range(seg_major):
            for j in range(seg_minor):
                a, b = rings[i], rings[(i + 1) % seg_major]
                self.bm.faces.new((a[j], b[j], b[(j + 1) % seg_minor], a[(j + 1) % seg_minor]))
        self._assign([v for ring in rings for v in ring], mat)

    def to_object(self, name, collection):
        mesh = bpy.data.meshes.new(name)
        self.bm.normal_update()
        self.bm.to_mesh(mesh)
        self.bm.free()
        for mat in self.materials:
            mesh.materials.append(mat)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        return obj


# ------------------------------------------------------------- 家具・建具


def build_chair(b, mats):
    wood = mats["main"]
    seat_h = 0.45
    b.box(wood, 0.42, 0.05, 0.42, 0, seat_h, 0)
    for sx in (-1, 1):
        for sz in (-1, 1):
            b.box(wood, 0.04, seat_h, 0.04, sx * 0.17, seat_h / 2, sz * 0.17)
    b.box(wood, 0.42, 0.45, 0.05, 0, seat_h + 0.25, -0.185)


def build_table(b, mats):
    wood = mats["main"]
    top_h = 0.72
    b.box(wood, 1.2, 0.05, 0.7, 0, top_h, 0)
    for sx in (-1, 1):
        for sz in (-1, 1):
            b.box(wood, 0.06, top_h, 0.06, sx * 0.53, top_h / 2, sz * 0.28)


def build_sofa(b, mats):
    fabric, leg = mats["main"], mats["leg"]
    leg_h = 0.08
    b.box(fabric, 1.6, 0.35, 0.75, 0, leg_h + 0.175, 0)
    b.box(fabric, 1.6, 0.45, 0.18, 0, leg_h + 0.35 + 0.225, -0.285)
    for sx in (-1, 1):
        b.box(fabric, 0.18, 0.25, 0.75, sx * 0.71, leg_h + 0.35 + 0.125, 0)
    for sx in (-1, 1):
        for sz in (-1, 1):
            b.box(leg, 0.06, leg_h, 0.06, sx * 0.72, leg_h / 2, sz * 0.3)


def build_bed(b, mats):
    wood, white = mats["main"], mats["linen"]
    b.box(wood, 1.05, 0.25, 2.1, 0, 0.125, 0)
    b.box(wood, 1.05, 0.4, 0.06, 0, 0.325, -1.02)
    b.box(white, 0.98, 0.16, 1.95, 0, 0.33, 0.02)
    b.box(white, 0.55, 0.09, 0.32, 0, 0.45, -0.75)


def build_shelf(b, mats):
    wood = mats["main"]
    h = 1.8
    b.box(wood, 0.02, h, 0.3, -0.39, h / 2, 0)
    b.box(wood, 0.02, h, 0.3, 0.39, h / 2, 0)
    b.box(wood, 0.8, h, 0.015, 0, h / 2, -0.1425)
    for i in range(5):
        b.box(wood, 0.76, 0.02, 0.3, 0, 0.01 + i * (h - 0.02) / 4, 0)


def build_door(b, mats):
    w, h, _ = OPENING_SPECS["door"]
    t = WALL_T + 0.02
    j = 0.05
    frame, panel, knob = mats["frame"], mats["main"], mats["knob"]
    b.box(frame, j, h, t, -(w - j) / 2, h / 2, 0)
    b.box(frame, j, h, t, (w - j) / 2, h / 2, 0)
    b.box(frame, w - j * 2, j, t, 0, h - j / 2, 0)  # 縦枠と重ならないよう内側だけ
    b.box(panel, w - j * 2, h - j, 0.05, 0, (h - j) / 2, 0)
    b.box(knob, 0.05, 0.05, 0.12, w / 2 - 0.16, 1.0, 0)


def build_window(b, mats):
    w, h, bottom = OPENING_SPECS["window"]
    t = WALL_T + 0.02
    j = 0.05
    cy = bottom + h / 2
    frame, glass = mats["main"], mats["glass"]
    b.box(frame, j, h, t, -(w - j) / 2, cy, 0)
    b.box(frame, j, h, t, (w - j) / 2, cy, 0)
    b.box(frame, w - j * 2, j, t, 0, bottom + j / 2, 0)  # 縦枠と重ならないよう内側だけ
    b.box(frame, w - j * 2, j, t, 0, bottom + h - j / 2, 0)
    b.box(frame, 0.04, h - j * 2, 0.06, 0, cy, 0)
    b.box(glass, (w - j * 2 - 0.04) / 2, h - j * 2, 0.02, -(w - j * 2 + 0.04) / 4, cy, 0)
    b.box(glass, (w - j * 2 - 0.04) / 2, h - j * 2, 0.02, (w - j * 2 + 0.04) / 4, cy, 0)


BUILDERS = {
    "chair": build_chair,
    "table": build_table,
    "sofa": build_sofa,
    "bed": build_bed,
    "shelf": build_shelf,
    "door": build_door,
    "window": build_window,
}


def object_materials(name, obj_type, color):
    mats = {"main": make_material(f"{name}_本体", color)}
    if obj_type == "sofa":
        mats["leg"] = make_material(f"{name}_脚", "#4a4239")
    elif obj_type == "bed":
        mats["linen"] = make_material(f"{name}_寝具", "#f2f0eb", roughness=0.9)
    elif obj_type == "door":
        mats["frame"] = make_material(f"{name}_枠", "#5a4a3a")
        mats["knob"] = make_material(f"{name}_ノブ", "#c9b037", roughness=0.3, metallic=1.0)
    elif obj_type == "window":
        mats["glass"] = make_material(f"{name}_ガラス", "#a9cfe4", roughness=0.05, glass=True)
    return mats


def build_primitive(b, obj_type, mat):
    """Web CAD の基本図形(原点が図形の中心)"""
    if obj_type == "sphere":
        b.uv_sphere(mat, 0.5)
    elif obj_type == "cylinder":
        b.cone(mat, 0.5, 0.5, 1.0)
    elif obj_type == "cone":
        b.cone(mat, 0.5, 0.0, 1.0)
    elif obj_type == "torus":
        b.torus(mat, 0.5, 0.2)
    else:
        b.box(mat, 1, 1, 1, 0, 0, 0)


# ------------------------------------------------------------------ 部屋


def ensure_cutter_collection(parent_collection):
    col = bpy.data.collections.get(CUTTER_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(CUTTER_COLLECTION)
        parent_collection.children.link(col)
        col.hide_render = True
    return col


def build_room_children(root, collection, cutters):
    """部屋の床・壁・天井を(寸法のカスタムプロパティから)作り直す"""
    for child in list(root.children):
        mesh = child.data
        bpy.data.objects.remove(child, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    W = root["幅_mm"] / 1000
    D = root["奥行_mm"] / 1000
    H = root["壁高_mm"] / 1000
    t = WALL_T
    F = FLOOR_T
    floor_mat = bpy.data.materials.get(root["床マテリアル"])
    wall_mat = bpy.data.materials.get("壁") or make_material("壁", WALL_COLOR, roughness=0.85)

    def part(name, mat, w, h, d, x, y, z, normal=None):
        b = MeshBuilder()
        b.box(mat, w, h, d, x, y, z)
        obj = b.to_object(f"{root.name}_{name}", collection)
        obj.parent = root
        if normal is not None:
            obj["webcad_wall_normal"] = normal  # 部屋ローカルの外向き法線(カットアウェイ用)
        return obj

    part("床", floor_mat, W, F, D, 0, F / 2, 0)
    walls = [
        part("壁_北", wall_mat, W, H, t, 0, F + H / 2, -D / 2 + t / 2, (0.0, 1.0, 0.0)),
        part("壁_南", wall_mat, W, H, t, 0, F + H / 2, D / 2 - t / 2, (0.0, -1.0, 0.0)),
        part("壁_西", wall_mat, t, H, D - t * 2, -W / 2 + t / 2, F + H / 2, 0, (-1.0, 0.0, 0.0)),
        part("壁_東", wall_mat, t, H, D - t * 2, W / 2 - t / 2, F + H / 2, 0, (1.0, 0.0, 0.0)),
    ]
    for wall in walls:
        mod = wall.modifiers.new("開口部", "BOOLEAN")
        mod.operation = "DIFFERENCE"
        mod.operand_type = "COLLECTION"
        mod.collection = cutters
        mod.solver = "EXACT"
    ceiling = part("天井", wall_mat, W, 0.02, D, 0, F + H + 0.01, 0)
    # 天井は室内パース用。俯瞰パースの邪魔にならないよう初期状態は非表示
    ceiling.hide_viewport = True
    ceiling.hide_render = True


def create_room(data, collection, cutters):
    params = data.get("params") or {"width": 4, "depth": 4, "height": 2.4}
    root = bpy.data.objects.new(data["name"], None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.3
    collection.objects.link(root)
    root["webcad_type"] = "room"
    root["幅_mm"] = round(params["width"] * 1000)
    root["奥行_mm"] = round(params["depth"] * 1000)
    root["壁高_mm"] = round(params["height"] * 1000)
    floor_mat = make_material(f"{data['name']}_床", data.get("color", DEFAULT_COLORS["room"]), roughness=0.5)
    root["床マテリアル"] = floor_mat.name
    build_room_children(root, collection, cutters)
    return root


def create_opening(data, collection, cutters):
    obj = create_furniture(data, collection)
    w, h, bottom = OPENING_SPECS[data["type"]]
    b = MeshBuilder()
    # 背中合わせの壁(隣室との境界)も貫通するよう奥行は壁厚 2 枚分より大きく取る
    b.box(None, w, h + 0.02, WALL_T * 2 + 0.12, 0, bottom + h / 2 - 0.01, 0)
    cutter = b.to_object(f"{data['name']}_カッター", cutters)
    cutter.parent = obj
    cutter.display_type = "WIRE"
    cutter.hide_render = True
    return obj


def create_furniture(data, collection):
    obj_type = data["type"]
    color = data.get("color") or DEFAULT_COLORS.get(obj_type, "#4f8ef7")
    b = MeshBuilder()
    builder = BUILDERS.get(obj_type)
    if builder:
        builder(b, object_materials(data["name"], obj_type, color))
    else:
        build_primitive(b, obj_type, make_material(f"{data['name']}_本体", color))
    obj = b.to_object(data["name"], collection)
    obj["webcad_type"] = obj_type
    return obj


# ---------------------------------------------------------- カットアウェイ


def _set_hidden(obj, hidden):
    obj.hide_viewport = hidden
    obj.hide_render = hidden


def apply_cutaway(scene, camera=None):
    """カメラ側を向いた壁を隠して室内が見えるようにする(Web CAD と同じ判定)。

    カメラが部屋の中にあるときは、その部屋の壁はすべて表示する。
    """
    camera = camera or scene.camera
    rooms = [o for o in scene.objects if o.get("webcad_type") == "room"]
    if camera is None or not rooms:
        return
    cam_pos = camera.matrix_world.translation
    is_ortho = camera.type == "CAMERA" and camera.data.type == "ORTHO"
    walls = []
    for room in rooms:
        local = room.matrix_world.inverted() @ cam_pos
        inside = abs(local.x) <= room["幅_mm"] / 2000 and abs(local.y) <= room["奥行_mm"] / 2000
        rot = room.matrix_world.to_3x3().normalized()
        for wall in room.children:
            normal = wall.get("webcad_wall_normal")
            if normal is None:
                continue
            hide = False
            if not inside and not is_ortho:
                n = rot @ Vector(normal)
                n.z = 0
                to_cam = cam_pos - wall.matrix_world @ _bound_center(wall)
                to_cam.z = 0
                if n.length > 0 and to_cam.length > 0:
                    hide = n.normalized().dot(to_cam.normalized()) > 0.35
            _set_hidden(wall, hide)
            walls.append(wall)

    # 隠した壁にしか付いていないドア・窓も隠す(隣室側の壁が見えていれば表示)
    for obj in scene.objects:
        if obj.get("webcad_type") not in OPENING_SPECS:
            continue
        p = obj.matrix_world.translation
        touching = [w for w in walls if _point_near_bounds(w, p, 0.2)]
        _set_hidden(obj, bool(touching) and all(w.hide_render for w in touching))


def _bound_center(obj):
    corners = [Vector(c) for c in obj.bound_box]
    return sum(corners, Vector()) / 8


def _point_near_bounds(obj, point, margin):
    local = obj.matrix_world.inverted() @ point
    corners = [Vector(c) for c in obj.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return all(lo[i] - margin <= local[i] <= hi[i] + margin for i in range(2))


@bpy.app.handlers.persistent
def _cutaway_before_render(scene, *_args):
    if scene.get("webcad_cutaway", False):
        apply_cutaway(scene)


# ------------------------------------------------------- カメラ・照明・設定


def create_camera(view, collection, scene):
    cam_data = bpy.data.cameras.new(view["name"])
    cam = bpy.data.objects.new(view["name"], cam_data)
    collection.objects.link(cam)
    cam_data.sensor_fit = "VERTICAL"
    target = to_bl_location(view["target"])
    if view.get("mode") == "plan":
        cam_data.type = "ORTHO"
        # Web CAD の平面図カメラは縦 16m を zoom で割った範囲を映す
        cam_data.ortho_scale = 16 / max(view.get("zoom", 1), 0.01)
        cam.location = (target.x, target.y, 30)
        cam.rotation_euler = (0, 0, 0)
        cam_data.clip_end = 100
    else:
        cam_data.angle_y = math.radians(50)
        cam.location = to_bl_location(view["position"])
        direction = target - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        cam_data.clip_start = 0.05
    return cam


def setup_world_and_lights(collection, scene):
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = hex_to_rgba("#cfdcea")
        background.inputs["Strength"].default_value = 1.0

    sun_data = bpy.data.lights.new("太陽光", "SUN")
    sun_data.energy = 3.5
    sun_data.angle = math.radians(2)
    sun = bpy.data.objects.new("太陽光", sun_data)
    collection.objects.link(sun)
    sun.location = to_bl_location((8, 14, 6))
    sun.rotation_euler = (-sun.location).to_track_quat("-Z", "Y").to_euler()


def setup_render(scene):
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    try:
        scene.cycles.use_denoising = True
    except AttributeError:
        pass


def frame_default_camera(objects):
    """保存アングルが無いときは間取り全体を斜め上から見るカメラを作る"""
    points = [o.location for o in objects] or [Vector((0, 0, 0))]
    center = sum(points, Vector()) / len(points)
    view = {
        "name": "全体パース",
        "mode": "persp",
        "position": (center.x + 7, 6, -center.y + 8),
        "target": (center.x, 0.8, -center.y),
    }
    return view


# ---------------------------------------------------------------- 本体


def import_webcad(filepath, context=None):
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != "web-cad":
        raise ValueError("Web CAD 形式の JSON ではありません")

    scene = (context or bpy.context).scene
    meta = data.get("meta") or {}
    title = meta.get("project") or "Web CAD"
    collection = bpy.data.collections.new(title)
    scene.collection.children.link(collection)
    cutters = ensure_cutter_collection(collection)

    created = []
    for item in data.get("objects", []):
        obj_type = item["type"]
        if obj_type == "room":
            obj = create_room(item, collection, cutters)
        elif obj_type in OPENING_SPECS:
            obj = create_opening(item, collection, cutters)
        else:
            obj = create_furniture(item, collection)
        obj.location = to_bl_location(item["position"])
        obj.rotation_euler = to_bl_rotation(item["rotation"])
        if obj_type != "room":
            obj.scale = to_bl_scale(item["scale"])
        else:
            # 部屋の大きさは寸法プロパティで表すので、スケールは寸法に焼き込む
            sx, sy, sz = item["scale"]
            if (sx, sy, sz) != (1, 1, 1):
                obj["幅_mm"] = round(obj["幅_mm"] * sx)
                obj["奥行_mm"] = round(obj["奥行_mm"] * sz)
                obj["壁高_mm"] = round(obj["壁高_mm"] * sy)
                build_room_children(obj, collection, cutters)
        created.append(obj)

    views = data.get("views") or [frame_default_camera(created)]
    cameras = [create_camera(v, collection, scene) for v in views]
    setup_world_and_lights(collection, scene)
    setup_render(scene)
    if cameras:
        scene.camera = cameras[0]
    scene["webcad_cutaway"] = True  # レンダー時にカメラ側の壁を自動で隠す
    bpy.context.view_layer.update()
    apply_cutaway(scene)
    return {"objects": len(created), "cameras": len(cameras), "title": title}


# ------------------------------------------------------------ UI / 登録


class WEBCAD_OT_import(bpy.types.Operator, ImportHelper):
    """Web CAD で保存した間取り(JSON)を読み込みます"""

    bl_idname = "import_scene.webcad"
    bl_label = "Web CAD を読み込み"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def execute(self, context):
        try:
            result = import_webcad(self.filepath, context)
        except Exception as error:  # noqa: BLE001 - UI にそのまま表示する
            self.report({"ERROR"}, f"読み込みに失敗しました: {error}")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"「{result['title']}」: {result['objects']} 個のオブジェクトと {result['cameras']} 台のカメラを作成しました",
        )
        return {"FINISHED"}


def find_room(obj):
    while obj is not None:
        if obj.get("webcad_type") == "room":
            return obj
        obj = obj.parent
    return None


class WEBCAD_OT_rebuild_room(bpy.types.Operator):
    """寸法(mm)を反映して部屋の床・壁・天井を作り直します"""

    bl_idname = "webcad.rebuild_room"
    bl_label = "部屋を再構築"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return find_room(context.active_object) is not None

    def execute(self, context):
        room = find_room(context.active_object)
        collection = room.users_collection[0]
        cutters = ensure_cutter_collection(collection)
        build_room_children(room, collection, cutters)
        context.view_layer.objects.active = room
        return {"FINISHED"}


class WEBCAD_OT_cutaway(bpy.types.Operator):
    """アクティブカメラから見て手前の壁を隠します(室内が見える外観パース用)"""

    bl_idname = "webcad.cutaway"
    bl_label = "カメラ側の壁を隠す"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        apply_cutaway(context.scene)
        return {"FINISHED"}


class WEBCAD_OT_toggle_ceilings(bpy.types.Operator):
    """全部屋の天井の表示を切り替えます(室内パース用)"""

    bl_idname = "webcad.toggle_ceilings"
    bl_label = "天井の表示切替"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ceilings = [o for o in bpy.data.objects if o.name.endswith("_天井") and find_room(o.parent)]
        show = any(o.hide_render for o in ceilings)
        for o in ceilings:
            o.hide_viewport = not show
            o.hide_render = not show
        return {"FINISHED"}


class WEBCAD_PT_panel(bpy.types.Panel):
    bl_label = "Web CAD"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Web CAD"

    def draw(self, context):
        layout = self.layout
        layout.operator(WEBCAD_OT_import.bl_idname, icon="IMPORT")
        room = find_room(context.active_object)
        box = layout.box()
        if room is None:
            box.label(text="部屋を選択すると寸法を編集できます")
        else:
            box.label(text=f"部屋: {room.name}", icon="HOME")
            box.prop(room, '["幅_mm"]', text="幅 (mm)")
            box.prop(room, '["奥行_mm"]', text="奥行 (mm)")
            box.prop(room, '["壁高_mm"]', text="壁高 (mm)")
            box.operator(WEBCAD_OT_rebuild_room.bl_idname, icon="FILE_REFRESH")
        col = layout.column(align=True)
        col.operator(WEBCAD_OT_cutaway.bl_idname, icon="VIEW_CAMERA")
        if "webcad_cutaway" in context.scene:
            col.prop(context.scene, '["webcad_cutaway"]', text="レンダー時に自動で隠す")
        layout.operator(WEBCAD_OT_toggle_ceilings.bl_idname, icon="HIDE_OFF")


def menu_import(self, context):
    self.layout.operator(WEBCAD_OT_import.bl_idname, text="Web CAD (.json)")


CLASSES = (
    WEBCAD_OT_import,
    WEBCAD_OT_rebuild_room,
    WEBCAD_OT_cutaway,
    WEBCAD_OT_toggle_ceilings,
    WEBCAD_PT_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    if _cutaway_before_render not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(_cutaway_before_render)


def unregister():
    if _cutaway_before_render in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(_cutaway_before_render)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


def _run_from_command_line():
    """blender --background --python webcad_importer.py -- 入力.json 出力.blend [レンダー.png]"""
    args = sys.argv[sys.argv.index("--") + 1 :]
    if not args:
        return False
    # 既定シーンの立方体・カメラ・ライトは不要なので消してから読み込む
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    result = import_webcad(args[0])
    print(f"Web CAD: {result}")
    if len(args) > 1:
        bpy.ops.wm.save_as_mainfile(filepath=args[1])
    if len(args) > 2:
        apply_cutaway(bpy.context.scene)
        bpy.context.scene.render.filepath = args[2]
        bpy.ops.render.render(write_still=True)
    return True


if __name__ == "__main__":
    if "--" in sys.argv and _run_from_command_line():
        pass
    else:
        register()
