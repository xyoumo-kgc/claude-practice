import * as THREE from 'three';

export type PrimitiveType = 'box' | 'sphere' | 'cylinder' | 'cone' | 'torus';

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
  version: 1;
  objects: CadObjectData[];
}

export const PRIMITIVE_LABELS: Record<PrimitiveType, string> = {
  box: '立方体',
  sphere: '球',
  cylinder: '円柱',
  cone: '円錐',
  torus: 'トーラス',
};

/** 底面が地面 (y=0) に接するように配置するための、原点から底面までの高さ */
export const BASE_HEIGHT: Record<PrimitiveType, number> = {
  box: 0.5,
  sphere: 0.5,
  cylinder: 0.5,
  cone: 0.5,
  torus: 0.2,
};

export const DEFAULT_COLOR = '#4f8ef7';

let counter = 0;

export function createGeometry(type: PrimitiveType): THREE.BufferGeometry {
  switch (type) {
    case 'box':
      return new THREE.BoxGeometry(1, 1, 1);
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
  }
}

export function createCadMesh(type: PrimitiveType, color = DEFAULT_COLOR): THREE.Mesh {
  const material = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.55,
    metalness: 0.1,
  });
  const mesh = new THREE.Mesh(createGeometry(type), material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  counter += 1;
  mesh.name = `${PRIMITIVE_LABELS[type]} ${counter}`;
  mesh.userData.cadType = type;
  return mesh;
}

export function isCadMesh(object: THREE.Object3D): object is THREE.Mesh {
  return (object as THREE.Mesh).isMesh && typeof object.userData.cadType === 'string';
}

export function serializeMesh(mesh: THREE.Mesh): CadObjectData {
  const material = mesh.material as THREE.MeshStandardMaterial;
  return {
    type: mesh.userData.cadType as PrimitiveType,
    name: mesh.name,
    position: mesh.position.toArray() as [number, number, number],
    rotation: [mesh.rotation.x, mesh.rotation.y, mesh.rotation.z],
    scale: mesh.scale.toArray() as [number, number, number],
    color: `#${material.color.getHexString()}`,
  };
}

export function deserializeMesh(data: CadObjectData): THREE.Mesh {
  const mesh = createCadMesh(data.type, data.color);
  mesh.name = data.name;
  mesh.position.fromArray(data.position);
  mesh.rotation.set(data.rotation[0], data.rotation[1], data.rotation[2]);
  mesh.scale.fromArray(data.scale);
  return mesh;
}
