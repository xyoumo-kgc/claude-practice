import * as THREE from 'three';

export type PrimitiveType =
  | 'box'
  | 'sphere'
  | 'cylinder'
  | 'cone'
  | 'torus'
  | 'room'
  | 'door'
  | 'window'
  | 'chair'
  | 'table'
  | 'sofa'
  | 'bed'
  | 'shelf';

export interface RoomParams {
  width: number;
  depth: number;
  height: number;
}

/** 壁の開口部(ドア・窓)。offset は壁の中心からの距離 */
export interface Opening {
  side: 'n' | 's' | 'w' | 'e';
  offset: number;
  width: number;
  bottom: number;
  height: number;
}

export interface CadObjectData {
  type: PrimitiveType;
  name: string;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
  color: string;
  params?: RoomParams;
}

export interface SavedViewData {
  name: string;
  mode: 'persp' | 'plan';
  position: [number, number, number];
  target: [number, number, number];
  zoom?: number;
}

export interface ProposalMeta {
  project?: string;
  customer?: string;
}

export interface SceneData {
  format: 'web-cad';
  version: number;
  objects: CadObjectData[];
  views?: SavedViewData[];
  meta?: ProposalMeta;
}

export const PRIMITIVE_LABELS: Record<PrimitiveType, string> = {
  box: '立方体',
  sphere: '球',
  cylinder: '円柱',
  cone: '円錐',
  torus: 'トーラス',
  room: '部屋',
  door: 'ドア',
  window: '窓',
  chair: 'イス',
  table: 'テーブル',
  sofa: 'ソファ',
  bed: 'ベッド',
  shelf: '棚',
};

/**
 * 底面が地面 (y=0) に接するように配置するための、原点から底面までの高さ。
 * 家具・部屋は底面が原点になるように組み立てるので 0。
 */
export const BASE_HEIGHT: Record<PrimitiveType, number> = {
  box: 0.5,
  sphere: 0.5,
  cylinder: 0.5,
  cone: 0.5,
  torus: 0.2,
  room: 0,
  door: 0,
  window: 0,
  chair: 0,
  table: 0,
  sofa: 0,
  bed: 0,
  shelf: 0,
};

/** 図形ごとのデフォルト色(recolorable な主要マテリアルに適用される) */
export const DEFAULT_COLORS: Partial<Record<PrimitiveType, string>> = {
  room: '#c9a97a', // 床材
  door: '#8a6a48',
  window: '#f0f2f4',
  chair: '#b5835a',
  table: '#8a6a48',
  sofa: '#6b8cae',
  bed: '#9a7b5c',
  shelf: '#a8845f',
};

export const DEFAULT_COLOR = '#4f8ef7';

export const WALL_THICKNESS = 0.12;
export const FLOOR_THICKNESS = 0.05;
export const DEFAULT_ROOM: RoomParams = { width: 4, depth: 4, height: 2.4 };

/** ドア・窓が壁に開ける開口部の寸法(bottom は床面からの高さ) */
export const OPENING_SPECS: Partial<Record<PrimitiveType, { width: number; height: number; bottom: number }>> = {
  door: { width: 0.9, height: 2.0, bottom: 0 },
  window: { width: 1.2, height: 1.0, bottom: 0.9 },
};

const WALL_COLOR = '#d8d5cd';
const FABRIC_WHITE = '#f2f0eb';
const DARK_LEG = '#4a4239';

let counter = 0;

export function createGeometry(type: PrimitiveType): THREE.BufferGeometry {
  switch (type) {
    case 'sphere':
      return new THREE.SphereGeometry(0.5, 32, 16);
    case 'cylinder':
      return new THREE.CylinderGeometry(0.5, 0.5, 1, 32);
    case 'cone':
      return new THREE.ConeGeometry(0.5, 1, 32);
    case 'torus': {
      const geometry = new THREE.TorusGeometry(0.5, 0.2, 16, 48);
      geometry.rotateX(-Math.PI / 2); // 地面に寝かせる
      return geometry;
    }
    default:
      return new THREE.BoxGeometry(1, 1, 1);
  }
}

function makeMaterial(color: string, recolorable = false): THREE.MeshStandardMaterial {
  const material = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.6,
    metalness: 0.05,
  });
  material.userData.recolorable = recolorable;
  return material;
}

/** 直方体パーツを親グループに追加するヘルパー(x/y/z は中心座標) */
function addBox(
  parent: THREE.Object3D,
  material: THREE.Material,
  w: number,
  h: number,
  d: number,
  x: number,
  y: number,
  z: number,
): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.position.set(x, y, z);
  parent.add(mesh);
  return mesh;
}

// ------------------------------------------------------------------ 部屋

const WALL_NORMALS: Record<Opening['side'], [number, number, number]> = {
  n: [0, 0, -1],
  s: [0, 0, 1],
  w: [-1, 0, 0],
  e: [1, 0, 0],
};

/** 1 面分の壁を、開口部を避けたボックスの集まりとして組み立てる */
function buildWall(
  room: THREE.Object3D,
  material: THREE.Material,
  side: Opening['side'],
  params: RoomParams,
  openings: Opening[],
): void {
  const { width: W, depth: D, height: H } = params;
  const t = WALL_THICKNESS;
  const F = FLOOR_THICKNESS;
  const horizontal = side === 'n' || side === 's'; // X 方向に伸びる壁か
  const L = horizontal ? W : D - t * 2;
  const wallPos = horizontal
    ? (side === 'n' ? -D / 2 + t / 2 : D / 2 - t / 2)
    : (side === 'w' ? -W / 2 + t / 2 : W / 2 - t / 2);
  const normal = new THREE.Vector3(...WALL_NORMALS[side]);

  const place = (u0: number, u1: number, y0: number, y1: number) => {
    if (u1 - u0 < 0.01 || y1 - y0 < 0.01) return;
    const len = u1 - u0;
    const h = y1 - y0;
    const c = (u0 + u1) / 2;
    const yc = (y0 + y1) / 2;
    const mesh = horizontal
      ? addBox(room, material, len, h, t, c, yc, wallPos)
      : addBox(room, material, t, h, len, wallPos, yc, c);
    mesh.userData.wallNormal = normal.clone();
  };

  const ops = openings
    .filter((o) => o.side === side)
    .sort((a, b) => a.offset - b.offset);

  let prev = -L / 2;
  for (const op of ops) {
    const u0 = Math.max(op.offset - op.width / 2, prev);
    const u1 = Math.min(op.offset + op.width / 2, L / 2);
    if (u1 <= u0) continue;
    place(prev, u0, F, F + H);
    place(u0, u1, F + op.bottom + op.height, F + H); // まぐさ(開口部の上)
    place(u0, u1, F, F + op.bottom); // 窓下の腰壁
    prev = u1;
  }
  place(prev, L / 2, F, F + H);
}

/** 部屋の床と壁を(開口部を反映して)作り直す */
export function rebuildRoom(room: THREE.Object3D, openings: Opening[], color?: string): void {
  const params = (room.userData.params ?? { ...DEFAULT_ROOM }) as RoomParams;
  const floorColor = color ?? (room.children.length > 0 ? getObjectColor(room) : DEFAULT_COLORS.room!);

  for (const child of [...room.children]) {
    const mesh = child as THREE.Mesh;
    mesh.geometry?.dispose();
    (mesh.material as THREE.Material | undefined)?.dispose?.();
  }
  room.clear();

  const floorMat = makeMaterial(floorColor, true);
  const wallMat = makeMaterial(WALL_COLOR);
  addBox(room, floorMat, params.width, FLOOR_THICKNESS, params.depth, 0, FLOOR_THICKNESS / 2, 0);
  for (const side of ['n', 's', 'w', 'e'] as const) {
    buildWall(room, wallMat, side, params, openings);
  }

  room.userData.params = params;
  room.userData.openings = openings;
  room.userData.buildKey = JSON.stringify({ params, openings });
  room.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });
}

// ------------------------------------------------------------- ドア・窓

/** ドア: 枠 + 扉 + ノブ(原点は床面・中央、壁に沿って X 方向) */
function buildDoor(group: THREE.Group, color: string): void {
  const spec = OPENING_SPECS.door!;
  const frameMat = makeMaterial('#5a4a3a');
  const panelMat = makeMaterial(color, true);
  const knobMat = makeMaterial('#c9b037');
  const W = spec.width;
  const H = spec.height;
  const T = WALL_THICKNESS + 0.02;
  const J = 0.05;
  addBox(group, frameMat, J, H, T, -(W - J) / 2, H / 2, 0);
  addBox(group, frameMat, J, H, T, (W - J) / 2, H / 2, 0);
  addBox(group, frameMat, W, J, T, 0, H - J / 2, 0);
  addBox(group, panelMat, W - J * 2, H - J, 0.05, 0, (H - J) / 2, 0);
  addBox(group, knobMat, 0.05, 0.05, 0.12, W / 2 - 0.16, 1.0, 0);
}

/** 窓: 枠 + 中桟 + 半透明ガラス(原点は床面・中央) */
function buildWindow(group: THREE.Group, color: string): void {
  const spec = OPENING_SPECS.window!;
  const frameMat = makeMaterial(color, true);
  const glassMat = new THREE.MeshStandardMaterial({
    color: '#a9cfe4',
    transparent: true,
    opacity: 0.35,
    roughness: 0.1,
    metalness: 0.1,
  });
  glassMat.userData.recolorable = false;
  const W = spec.width;
  const H = spec.height;
  const B = spec.bottom;
  const T = WALL_THICKNESS + 0.02;
  const J = 0.05;
  const cy = B + H / 2;
  addBox(group, frameMat, J, H, T, -(W - J) / 2, cy, 0);
  addBox(group, frameMat, J, H, T, (W - J) / 2, cy, 0);
  addBox(group, frameMat, W, J, T, 0, B + J / 2, 0);
  addBox(group, frameMat, W, J, T, 0, B + H - J / 2, 0);
  addBox(group, frameMat, 0.04, H - J * 2, 0.06, 0, cy, 0);
  addBox(group, glassMat, W - J * 2, H - J * 2, 0.02, 0, cy, 0);
}

// ------------------------------------------------------------------ 家具

/** イス: 座面 + 4本脚 + 背もたれ */
function buildChair(group: THREE.Group, color: string): void {
  const wood = makeMaterial(color, true);
  const seatH = 0.45;
  addBox(group, wood, 0.42, 0.05, 0.42, 0, seatH, 0);
  const legOffset = 0.17;
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      addBox(group, wood, 0.04, seatH, 0.04, sx * legOffset, seatH / 2, sz * legOffset);
    }
  }
  addBox(group, wood, 0.42, 0.45, 0.05, 0, seatH + 0.25, -0.185);
}

/** テーブル: 天板 + 4本脚 */
function buildTable(group: THREE.Group, color: string): void {
  const wood = makeMaterial(color, true);
  const topH = 0.72;
  addBox(group, wood, 1.2, 0.05, 0.7, 0, topH, 0);
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      addBox(group, wood, 0.06, topH, 0.06, sx * 0.53, topH / 2, sz * 0.28);
    }
  }
}

/** 2人掛けソファ: 座面 + 背もたれ + 肘掛け + 脚 */
function buildSofa(group: THREE.Group, color: string): void {
  const fabric = makeMaterial(color, true);
  const legMat = makeMaterial(DARK_LEG);
  const legH = 0.08;
  addBox(group, fabric, 1.6, 0.35, 0.75, 0, legH + 0.175, 0);
  addBox(group, fabric, 1.6, 0.45, 0.18, 0, legH + 0.35 + 0.225, -0.285);
  for (const sx of [-1, 1]) {
    addBox(group, fabric, 0.18, 0.25, 0.75, sx * 0.71, legH + 0.35 + 0.125, 0);
  }
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      addBox(group, legMat, 0.06, legH, 0.06, sx * 0.72, legH / 2, sz * 0.3);
    }
  }
}

/** シングルベッド: フレーム + マットレス + 枕 */
function buildBed(group: THREE.Group, color: string): void {
  const wood = makeMaterial(color, true);
  const white = makeMaterial(FABRIC_WHITE);
  addBox(group, wood, 1.05, 0.25, 2.1, 0, 0.125, 0);
  addBox(group, wood, 1.05, 0.4, 0.06, 0, 0.325, -1.02); // ヘッドボード
  addBox(group, white, 0.98, 0.16, 1.95, 0, 0.33, 0.02);
  addBox(group, white, 0.55, 0.09, 0.32, 0, 0.45, -0.75); // 枕
}

/** 棚: 側板 + 背板 + 棚板 */
function buildShelf(group: THREE.Group, color: string): void {
  const wood = makeMaterial(color, true);
  const H = 1.8;
  addBox(group, wood, 0.02, H, 0.3, -0.39, H / 2, 0);
  addBox(group, wood, 0.02, H, 0.3, 0.39, H / 2, 0);
  addBox(group, wood, 0.8, H, 0.015, 0, H / 2, -0.1425);
  for (let i = 0; i <= 4; i += 1) {
    addBox(group, wood, 0.76, 0.02, 0.3, 0, 0.01 + (i * (H - 0.02)) / 4, 0);
  }
}

const GROUP_BUILDERS: Partial<Record<PrimitiveType, (group: THREE.Group, color: string) => void>> = {
  door: buildDoor,
  window: buildWindow,
  chair: buildChair,
  table: buildTable,
  sofa: buildSofa,
  bed: buildBed,
  shelf: buildShelf,
};

// -------------------------------------------------------------- 生成/操作

/**
 * CAD オブジェクト(単純図形は Mesh、部屋・家具は Group)を生成する。
 * ghost=true のときは配置プレビュー用: 名前を付けず、連番カウンターも消費しない。
 */
export function createCadObject(
  type: PrimitiveType,
  color?: string,
  ghost = false,
  params?: RoomParams,
): THREE.Object3D {
  const effectiveColor = color ?? DEFAULT_COLORS[type] ?? DEFAULT_COLOR;
  let object: THREE.Object3D;

  if (type === 'room') {
    const group = new THREE.Group();
    group.userData.params = { ...(params ?? DEFAULT_ROOM) };
    rebuildRoom(group, [], effectiveColor);
    object = group;
  } else {
    const builder = GROUP_BUILDERS[type];
    if (builder) {
      const group = new THREE.Group();
      builder(group, effectiveColor);
      object = group;
    } else {
      object = new THREE.Mesh(createGeometry(type), makeMaterial(effectiveColor, true));
    }
  }

  object.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });

  object.userData.cadType = type;
  if (!ghost) {
    counter += 1;
    object.name = `${PRIMITIVE_LABELS[type]} ${counter}`;
  }
  return object;
}

export function isCadObject(object: THREE.Object3D): boolean {
  return typeof object.userData.cadType === 'string';
}

/** オブジェクトを構成する全マテリアルを重複なく列挙する */
export function objectMaterials(object: THREE.Object3D): THREE.MeshStandardMaterial[] {
  const materials = new Set<THREE.MeshStandardMaterial>();
  object.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (mesh.isMesh) materials.add(mesh.material as THREE.MeshStandardMaterial);
  });
  return [...materials];
}

/** 色編集の対象になる主要マテリアル(recolorable)だけを列挙する */
function recolorableMaterials(object: THREE.Object3D): THREE.MeshStandardMaterial[] {
  return objectMaterials(object).filter((m) => m.userData.recolorable);
}

export function getObjectColor(object: THREE.Object3D): string {
  const primary = recolorableMaterials(object)[0] ?? objectMaterials(object)[0];
  return primary ? `#${primary.color.getHexString()}` : DEFAULT_COLOR;
}

export function setObjectColor(object: THREE.Object3D, color: string): void {
  for (const material of recolorableMaterials(object)) {
    material.color.set(color);
  }
}

export function serializeObject(object: THREE.Object3D): CadObjectData {
  const data: CadObjectData = {
    type: object.userData.cadType as PrimitiveType,
    name: object.name,
    position: object.position.toArray() as [number, number, number],
    rotation: [object.rotation.x, object.rotation.y, object.rotation.z],
    scale: object.scale.toArray() as [number, number, number],
    color: getObjectColor(object),
  };
  if (object.userData.params) {
    data.params = { ...(object.userData.params as RoomParams) };
  }
  return data;
}

export function deserializeObject(data: CadObjectData): THREE.Object3D {
  const object = createCadObject(data.type, data.color, false, data.params);
  object.name = data.name;
  object.position.fromArray(data.position);
  object.rotation.set(data.rotation[0], data.rotation[1], data.rotation[2]);
  object.scale.fromArray(data.scale);
  return object;
}
