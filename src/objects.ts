import * as THREE from 'three';

export type PrimitiveType =
  | 'box'
  | 'sphere'
  | 'cylinder'
  | 'cone'
  | 'torus'
  | 'room'
  | 'chair'
  | 'table'
  | 'sofa'
  | 'bed'
  | 'shelf';

export interface CadObjectData {
  type: PrimitiveType;
  name: string;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
  color: string;
}

export interface SceneData {
  format: 'web-cad';
  version: number;
  objects: CadObjectData[];
}

export const PRIMITIVE_LABELS: Record<PrimitiveType, string> = {
  box: '立方体',
  sphere: '球',
  cylinder: '円柱',
  cone: '円錐',
  torus: 'トーラス',
  room: '部屋',
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
  chair: 0,
  table: 0,
  sofa: 0,
  bed: 0,
  shelf: 0,
};

/** 図形ごとのデフォルト色(recolorable な主要マテリアルに適用される) */
export const DEFAULT_COLORS: Partial<Record<PrimitiveType, string>> = {
  room: '#c9a97a', // 床材
  chair: '#b5835a',
  table: '#8a6a48',
  sofa: '#6b8cae',
  bed: '#9a7b5c',
  shelf: '#a8845f',
};

export const DEFAULT_COLOR = '#4f8ef7';

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

// ------------------------------------------------------------------ 家具

/** 4×4m の部屋: 床スラブ + 四方の腰壁(中が見えるように高さ 1.2m) */
function buildRoom(group: THREE.Group, color: string): void {
  const floorMat = makeMaterial(color, true);
  const wallMat = makeMaterial(WALL_COLOR);
  const W = 4;
  const D = 4;
  const H = 1.2; // 壁の高さ
  const T = 0.12; // 壁の厚み
  const F = 0.06; // 床の厚み

  addBox(group, floorMat, W, F, D, 0, F / 2, 0);
  addBox(group, wallMat, W, H, T, 0, F + H / 2, -D / 2 + T / 2);
  addBox(group, wallMat, W, H, T, 0, F + H / 2, D / 2 - T / 2);
  addBox(group, wallMat, T, H, D - T * 2, -W / 2 + T / 2, F + H / 2, 0);
  addBox(group, wallMat, T, H, D - T * 2, W / 2 - T / 2, F + H / 2, 0);
}

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

const FURNITURE_BUILDERS: Partial<Record<PrimitiveType, (group: THREE.Group, color: string) => void>> = {
  room: buildRoom,
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
export function createCadObject(type: PrimitiveType, color?: string, ghost = false): THREE.Object3D {
  const effectiveColor = color ?? DEFAULT_COLORS[type] ?? DEFAULT_COLOR;
  let object: THREE.Object3D;

  const builder = FURNITURE_BUILDERS[type];
  if (builder) {
    const group = new THREE.Group();
    builder(group, effectiveColor);
    object = group;
  } else {
    object = new THREE.Mesh(createGeometry(type), makeMaterial(effectiveColor, true));
  }

  object.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      child.castShadow = true;
      child.receiveShadow = true;
    }
  });

  if (!ghost) {
    counter += 1;
    object.name = `${PRIMITIVE_LABELS[type]} ${counter}`;
    object.userData.cadType = type;
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
  return {
    type: object.userData.cadType as PrimitiveType,
    name: object.name,
    position: object.position.toArray() as [number, number, number],
    rotation: [object.rotation.x, object.rotation.y, object.rotation.z],
    scale: object.scale.toArray() as [number, number, number],
    color: getObjectColor(object),
  };
}

export function deserializeObject(data: CadObjectData): THREE.Object3D {
  const object = createCadObject(data.type, data.color);
  object.name = data.name;
  object.position.fromArray(data.position);
  object.rotation.set(data.rotation[0], data.rotation[1], data.rotation[2]);
  object.scale.fromArray(data.scale);
  return object;
}
