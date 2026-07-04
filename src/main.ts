import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js';
import { History, type Command } from './history';
import {
  BASE_HEIGHT,
  FLOOR_THICKNESS,
  OPENING_SPECS,
  PRIMITIVE_LABELS,
  WALL_THICKNESS,
  createCadObject,
  deserializeObject,
  getObjectColor,
  isCadObject,
  objectMaterials,
  rebuildRoom,
  serializeObject,
  setObjectColor,
  type Opening,
  type PrimitiveType,
  type ProposalMeta,
  type RoomParams,
  type SavedViewData,
  type SceneData,
} from './objects';
import './style.css';

const GRID_SNAP = 0.5;
const ROTATION_SNAP = THREE.MathUtils.degToRad(15);
const SCALE_SNAP = 0.1;
const CLICK_TOLERANCE_PX = 5;
const WALL_SNAP_DISTANCE = 0.25;
const BG_EDIT = '#22242a';
const BG_PRESENT = '#f4f5f7';

const _v1 = new THREE.Vector3();
const _v2 = new THREE.Vector3();
const _q1 = new THREE.Quaternion();

interface TransformState {
  position: THREE.Vector3;
  rotation: THREE.Euler;
  scale: THREE.Vector3;
}

function captureTransform(object: THREE.Object3D): TransformState {
  return {
    position: object.position.clone(),
    rotation: object.rotation.clone(),
    scale: object.scale.clone(),
  };
}

function applyTransform(object: THREE.Object3D, state: TransformState): void {
  object.position.copy(state.position);
  object.rotation.copy(state.rotation);
  object.scale.copy(state.scale);
}

function transformEquals(a: TransformState, b: TransformState): boolean {
  return (
    a.position.equals(b.position) &&
    a.rotation.equals(b.rotation) &&
    a.scale.equals(b.scale)
  );
}

function element<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`要素が見つかりません: #${id}`);
  return el as T;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}

class CadApp {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly planCamera: THREE.OrthographicCamera;
  private readonly orbit: OrbitControls;
  private readonly planOrbit: OrbitControls;
  private readonly transform: TransformControls;
  private readonly raycaster = new THREE.Raycaster();
  private readonly groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  /** ユーザーが作成した CAD オブジェクトだけを入れるグループ */
  private readonly objects = new THREE.Group();
  /** 平面図モードで表示する寸法線(部屋ごとのサブグループ) */
  private readonly dimensions = new THREE.Group();
  private readonly history = new History();

  private readonly viewport = element<HTMLDivElement>('viewport');
  private readonly statusBar = element<HTMLElement>('status');

  private gridHelper!: THREE.GridHelper;
  private axesHelper!: THREE.AxesHelper;
  private sun!: THREE.DirectionalLight;

  private activeTool: PrimitiveType | null = null;
  private ghost: THREE.Object3D | null = null;
  private ghostRotation = 0;
  private selected: THREE.Object3D | null = null;
  private snapEnabled = true;
  private planMode = false;
  private dragStartState: TransformState | null = null;
  private pointerDown: { x: number; y: number } | null = null;
  private readonly collided = new Set<THREE.Object3D>();
  private savedViews: SavedViewData[] = [];

  constructor() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.viewport.appendChild(this.renderer.domElement);

    this.scene.background = new THREE.Color(BG_EDIT);
    this.scene.add(this.objects);
    this.dimensions.visible = false;
    this.scene.add(this.dimensions);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 500);
    this.camera.position.set(7, 6, 9);

    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.target.set(0, 0.5, 0);
    this.orbit.enableDamping = true;

    // 平面図用の正射投影カメラ(真上から、Z- が画面上方向)
    this.planCamera = new THREE.OrthographicCamera(-8, 8, 8, -8, 0.1, 100);
    this.planCamera.position.set(0, 30, 0);
    this.planCamera.up.set(0, 0, -1);
    this.planCamera.lookAt(0, 0, 0);
    this.planOrbit = new OrbitControls(this.planCamera, this.renderer.domElement);
    this.planOrbit.enableRotate = false;
    this.planOrbit.screenSpacePanning = false;
    this.planOrbit.enabled = false;

    this.transform = new TransformControls(this.camera, this.renderer.domElement);
    this.scene.add(this.transform.getHelper());

    this.setupEnvironment();
    this.setupTransformEvents();
    this.setupPointerEvents();
    this.setupToolbar();
    this.setupPanel();
    this.setupKeyboard();
    this.applySnapSettings();

    this.history.onChange = () => {
      this.updateToolbarState();
      this.updateRooms();
      this.updateCollisions();
    };
    this.updateToolbarState();

    window.addEventListener('resize', () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop(() => {
      (this.planMode ? this.planOrbit : this.orbit).update();
      this.updateWallVisibility();
      this.syncDimensions();
      this.renderer.render(this.scene, this.activeCamera);
    });

    this.setStatus('準備完了。「部屋」を置いて、ドア・窓・家具を配置してみてください。');
  }

  private get activeCamera(): THREE.Camera {
    return this.planMode ? this.planCamera : this.camera;
  }

  // ---------------------------------------------------------------- 環境

  private setupEnvironment(): void {
    const hemisphere = new THREE.HemisphereLight('#cfd8e6', '#3a3f4a', 0.9);
    this.scene.add(hemisphere);

    this.sun = new THREE.DirectionalLight('#ffffff', 1.6);
    this.sun.position.set(8, 14, 6);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.camera.left = -20;
    this.sun.shadow.camera.right = 20;
    this.sun.shadow.camera.top = 20;
    this.sun.shadow.camera.bottom = -20;
    this.scene.add(this.sun);

    this.gridHelper = new THREE.GridHelper(40, 80, '#5a6070', '#33363f');
    this.scene.add(this.gridHelper);
    this.axesHelper = new THREE.AxesHelper(2.5);
    this.scene.add(this.axesHelper);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.ShadowMaterial({ opacity: 0.35 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);
  }

  private resize(): void {
    const { clientWidth, clientHeight } = this.viewport;
    const aspect = clientWidth / Math.max(clientHeight, 1);
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
    this.planCamera.left = -8 * aspect;
    this.planCamera.right = 8 * aspect;
    this.planCamera.updateProjectionMatrix();
    this.renderer.setSize(clientWidth, clientHeight);
  }

  // ------------------------------------------------------------ ステータス

  private setStatus(message: string): void {
    this.statusBar.textContent = message;
  }

  // -------------------------------------------------------------- スナップ

  private applySnapSettings(): void {
    this.transform.setTranslationSnap(this.snapEnabled ? GRID_SNAP : null);
    this.transform.setRotationSnap(this.snapEnabled ? ROTATION_SNAP : null);
    this.transform.setScaleSnap(this.snapEnabled ? SCALE_SNAP : null);
  }

  private snapValue(value: number): number {
    return this.snapEnabled ? Math.round(value / GRID_SNAP) * GRID_SNAP : value;
  }

  // ------------------------------------------------------------ 部屋の管理

  private rooms(): THREE.Object3D[] {
    return this.cadObjects().filter((o) => o.userData.cadType === 'room');
  }

  private roomAt(worldPoint: THREE.Vector3): THREE.Object3D | null {
    for (const room of this.rooms()) {
      const params = room.userData.params as RoomParams;
      room.updateMatrixWorld();
      const local = room.worldToLocal(worldPoint.clone());
      if (Math.abs(local.x) <= params.width / 2 && Math.abs(local.z) <= params.depth / 2) {
        return room;
      }
    }
    return null;
  }

  /** ドア・窓の位置から各部屋の開口部を計算し、変化があれば壁を作り直す */
  private updateRooms(): void {
    const openers = this.cadObjects().filter(
      (o) => o.userData.cadType === 'door' || o.userData.cadType === 'window',
    );
    for (const room of this.rooms()) {
      const params = room.userData.params as RoomParams;
      const t = WALL_THICKNESS;
      const halfW = params.width / 2;
      const halfD = params.depth / 2;
      room.updateMatrixWorld();

      const openings: Opening[] = [];
      for (const opener of openers) {
        const spec = OPENING_SPECS[opener.userData.cadType as PrimitiveType];
        if (!spec) continue;
        const local = room.worldToLocal(opener.getWorldPosition(_v1).clone());
        let side: Opening['side'] | null = null;
        let offset = 0;
        if (Math.abs(local.z - (-halfD + t / 2)) < t && Math.abs(local.x) < halfW) {
          side = 'n';
          offset = local.x;
        } else if (Math.abs(local.z - (halfD - t / 2)) < t && Math.abs(local.x) < halfW) {
          side = 's';
          offset = local.x;
        } else if (Math.abs(local.x - (-halfW + t / 2)) < t && Math.abs(local.z) < halfD) {
          side = 'w';
          offset = local.z;
        } else if (Math.abs(local.x - (halfW - t / 2)) < t && Math.abs(local.z) < halfD) {
          side = 'e';
          offset = local.z;
        }
        if (!side) continue;
        openings.push({
          side,
          offset: round3(offset),
          width: round3(spec.width * opener.scale.x),
          bottom: spec.bottom,
          height: round3(spec.height * opener.scale.y),
        });
      }

      openings.sort((a, b) => (a.side + a.offset).localeCompare(b.side + b.offset));
      const key = JSON.stringify({ params, openings });
      if (room.userData.buildKey !== key) {
        rebuildRoom(room, openings);
      }
    }
    this.refreshTints();
    this.updateDimensions();
  }

  // ------------------------------------------------------------ 寸法線

  /** 寸法値ラベル(mm 表記)のスプライトを作る */
  private makeDimLabel(text: string, vertical = false): THREE.Sprite {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 96;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#ffffff';
    const r = 16;
    ctx.beginPath();
    ctx.roundRect(4, 4, canvas.width - 8, canvas.height - 8, r);
    ctx.fill();
    ctx.strokeStyle = '#2f80ed';
    ctx.lineWidth = 4;
    ctx.stroke();
    ctx.fillStyle = '#1f2933';
    ctx.font = 'bold 52px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, canvas.width / 2, canvas.height / 2 + 2);
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({ map: texture, depthTest: false });
    if (vertical) material.rotation = Math.PI / 2;
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(0.95, 0.36, 1);
    sprite.renderOrder = 11;
    return sprite;
  }

  /** 1 部屋分の寸法線(幅・奥行、mm 表記)を組み立てる */
  private buildRoomDimensions(room: THREE.Object3D): THREE.Group {
    const params = room.userData.params as RoomParams;
    const group = new THREE.Group();
    const W = params.width;
    const D = params.depth;
    const off = 0.55; // 部屋の外側へのオフセット
    const tick = 0.12;
    const y = 0.02;
    const mm = (v: number) => Math.round(v * 1000).toLocaleString('ja-JP');

    const points: number[] = [];
    // 幅の寸法線(部屋の手前 = +z 側)
    const z1 = D / 2 + off;
    points.push(-W / 2, y, z1, W / 2, y, z1);
    points.push(-W / 2, y, z1 - tick, -W / 2, y, z1 + tick);
    points.push(W / 2, y, z1 - tick, W / 2, y, z1 + tick);
    points.push(-W / 2, y, D / 2, -W / 2, y, z1); // 補助線
    points.push(W / 2, y, D / 2, W / 2, y, z1);
    // 奥行の寸法線(部屋の左 = -x 側)
    const x1 = -W / 2 - off;
    points.push(x1, y, -D / 2, x1, y, D / 2);
    points.push(x1 - tick, y, -D / 2, x1 + tick, y, -D / 2);
    points.push(x1 - tick, y, D / 2, x1 + tick, y, D / 2);
    points.push(-W / 2, y, -D / 2, x1, y, -D / 2);
    points.push(-W / 2, y, D / 2, x1, y, D / 2);

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
    const lines = new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ color: 0x2f80ed, depthTest: false }),
    );
    lines.renderOrder = 10;
    group.add(lines);

    const widthLabel = this.makeDimLabel(mm(W));
    widthLabel.position.set(0, y, z1 + 0.4);
    const depthLabel = this.makeDimLabel(mm(D), true);
    depthLabel.position.set(x1 - 0.4, y, 0);
    group.add(widthLabel, depthLabel);

    group.userData.room = room;
    return group;
  }

  /** 寸法線を全部屋分作り直す(部屋の追加・削除・寸法変更時) */
  private updateDimensions(): void {
    for (const child of [...this.dimensions.children]) {
      child.traverse((node) => {
        const mesh = node as THREE.Mesh;
        mesh.geometry?.dispose();
        const material = mesh.material as THREE.Material & { map?: THREE.Texture };
        material?.map?.dispose();
        material?.dispose?.();
      });
    }
    this.dimensions.clear();
    for (const room of this.rooms()) {
      this.dimensions.add(this.buildRoomDimensions(room));
    }
    this.syncDimensions();
  }

  /** 寸法線の位置・向きを部屋に追従させる(毎フレーム、再構築なしで安価に) */
  private syncDimensions(): void {
    for (const child of this.dimensions.children) {
      const room = child.userData.room as THREE.Object3D | undefined;
      if (!room) continue;
      child.position.copy(room.position);
      child.quaternion.copy(room.quaternion);
    }
  }

  /** カメラ側を向いている壁を隠して、部屋の中が見えるようにする */
  private updateWallVisibility(): void {
    for (const room of this.rooms()) {
      room.getWorldQuaternion(_q1);
      for (const child of room.children) {
        const normal = child.userData.wallNormal as THREE.Vector3 | undefined;
        if (!normal) continue;
        if (this.planMode) {
          child.visible = true;
          continue;
        }
        _v1.copy(normal).applyQuaternion(_q1);
        child.getWorldPosition(_v2);
        _v2.subVectors(this.camera.position, _v2).normalize();
        child.visible = _v1.dot(_v2) < 0.35;
      }
    }
  }

  /** ドア・窓を最寄りの壁の中心線に吸着させ、向きを壁に合わせる */
  private snapOpeningToWall(object: THREE.Object3D): void {
    const spec = OPENING_SPECS[object.userData.cadType as PrimitiveType];
    if (!spec) return;
    let best: { room: THREE.Object3D; side: Opening['side']; dist: number } | null = null;
    for (const room of this.rooms()) {
      const params = room.userData.params as RoomParams;
      const t = WALL_THICKNESS;
      const halfW = params.width / 2;
      const halfD = params.depth / 2;
      room.updateMatrixWorld();
      const local = room.worldToLocal(object.position.clone());
      if (Math.abs(local.x) > halfW + 0.6 || Math.abs(local.z) > halfD + 0.6) continue;
      const candidates: Array<[Opening['side'], number]> = [
        ['n', Math.abs(local.z - (-halfD + t / 2))],
        ['s', Math.abs(local.z - (halfD - t / 2))],
        ['w', Math.abs(local.x - (-halfW + t / 2))],
        ['e', Math.abs(local.x - (halfW - t / 2))],
      ];
      for (const [side, dist] of candidates) {
        if (dist < 0.6 && (!best || dist < best.dist)) {
          best = { room, side, dist };
        }
      }
    }
    if (!best) return;

    const { room, side } = best;
    const params = room.userData.params as RoomParams;
    const t = WALL_THICKNESS;
    const halfW = params.width / 2;
    const halfD = params.depth / 2;
    const local = room.worldToLocal(object.position.clone());
    const halfOpening = (spec.width * object.scale.x) / 2;

    if (side === 'n' || side === 's') {
      local.z = side === 'n' ? -halfD + t / 2 : halfD - t / 2;
      local.x = THREE.MathUtils.clamp(local.x, -halfW + t + halfOpening, halfW - t - halfOpening);
    } else {
      local.x = side === 'w' ? -halfW + t / 2 : halfW - t / 2;
      local.z = THREE.MathUtils.clamp(local.z, -halfD + t + halfOpening, halfD - t - halfOpening);
    }
    local.y = FLOOR_THICKNESS;
    object.position.copy(room.localToWorld(local));
    const wallRot = side === 'n' || side === 's' ? 0 : Math.PI / 2;
    object.rotation.set(0, room.rotation.y + wallRot, 0);
  }

  /** 家具を部屋の壁の内側面に吸着させる */
  private snapFurnitureToWalls(object: THREE.Object3D): void {
    const room = this.roomAt(object.position);
    if (!room) return;
    const params = room.userData.params as RoomParams;
    const box = new THREE.Box3().setFromObject(object);
    const halfX = (box.max.x - box.min.x) / 2;
    const halfZ = (box.max.z - box.min.z) / 2;
    const innerX = params.width / 2 - WALL_THICKNESS;
    const innerZ = params.depth / 2 - WALL_THICKNESS;
    room.updateMatrixWorld();
    const local = room.worldToLocal(object.position.clone());

    if (innerX - (local.x + halfX) < WALL_SNAP_DISTANCE) local.x = innerX - halfX;
    else if (local.x - halfX + innerX < WALL_SNAP_DISTANCE) local.x = -innerX + halfX;
    if (innerZ - (local.z + halfZ) < WALL_SNAP_DISTANCE) local.z = innerZ - halfZ;
    else if (local.z - halfZ + innerZ < WALL_SNAP_DISTANCE) local.z = -innerZ + halfZ;

    object.position.copy(room.localToWorld(local));
  }

  // ------------------------------------------------------ 衝突チェック

  private collidables(): THREE.Object3D[] {
    return this.cadObjects().filter(
      (o) => !['room', 'door', 'window'].includes(o.userData.cadType as string),
    );
  }

  private updateCollisions(): void {
    const items = this.collidables();
    const boxes = items.map((o) => new THREE.Box3().setFromObject(o).expandByScalar(-0.02));
    this.collided.clear();
    for (let i = 0; i < items.length; i += 1) {
      for (let j = i + 1; j < items.length; j += 1) {
        if (boxes[i].intersectsBox(boxes[j])) {
          this.collided.add(items[i]);
          this.collided.add(items[j]);
        }
      }
    }
    this.refreshTints();
    if (this.selected && this.collided.has(this.selected)) {
      this.setStatus(`⚠ 「${this.selected.name}」が他の家具と重なっています`);
    }
  }

  /** 選択(青)と衝突(赤)のハイライトをまとめて再適用する */
  private refreshTints(): void {
    for (const object of this.cadObjects()) {
      const hex = this.collided.has(object)
        ? 0x8b1f1f
        : object === this.selected
          ? 0x1a4d99
          : 0x000000;
      for (const material of objectMaterials(object)) {
        material.emissive.setHex(hex);
      }
    }
  }

  // ---------------------------------------------------------------- 選択

  private select(object: THREE.Object3D | null): void {
    if (this.selected === object) {
      this.refreshTints();
      return;
    }
    this.selected = object;
    if (object) {
      this.transform.attach(object);
      this.setStatus(`「${object.name}」を選択中`);
    } else {
      this.transform.detach();
    }
    this.refreshTints();
    this.syncPanel();
    this.updateToolbarState();
  }

  // ------------------------------------------------------------- コマンド

  private makeAddCommand(object: THREE.Object3D, label: string): Command {
    return {
      label,
      redo: () => {
        this.objects.add(object);
        this.select(object);
      },
      undo: () => {
        if (this.selected === object) this.select(null);
        this.objects.remove(object);
      },
    };
  }

  private makeDeleteCommand(object: THREE.Object3D): Command {
    return {
      label: '削除',
      redo: () => {
        if (this.selected === object) this.select(null);
        this.objects.remove(object);
      },
      undo: () => {
        this.objects.add(object);
        this.select(object);
      },
    };
  }

  private makeTransformCommand(
    object: THREE.Object3D,
    before: TransformState,
    after: TransformState,
  ): Command {
    return {
      label: '変形',
      redo: () => {
        applyTransform(object, after);
        this.syncPanel();
      },
      undo: () => {
        applyTransform(object, before);
        this.syncPanel();
      },
    };
  }

  // ------------------------------------------------------ ギズモのイベント

  private setupTransformEvents(): void {
    this.transform.addEventListener('dragging-changed', (event) => {
      const dragging = event.value as boolean;
      this.orbit.enabled = !dragging && !this.planMode;
      this.planOrbit.enabled = !dragging && this.planMode;
    });
    this.transform.addEventListener('mouseDown', () => {
      if (this.selected) this.dragStartState = captureTransform(this.selected);
    });
    this.transform.addEventListener('mouseUp', () => {
      if (!this.selected || !this.dragStartState) return;
      const type = this.selected.userData.cadType as string;
      if (type === 'door' || type === 'window') {
        this.snapOpeningToWall(this.selected);
      } else if (type !== 'room' && this.transform.mode === 'translate') {
        this.snapFurnitureToWalls(this.selected);
      }
      const after = captureTransform(this.selected);
      if (!transformEquals(this.dragStartState, after)) {
        // 変形はドラッグ中に適用済みなので execute=false で履歴にだけ積む
        this.history.push(this.makeTransformCommand(this.selected, this.dragStartState, after), false);
      }
      this.dragStartState = null;
    });
    this.transform.addEventListener('objectChange', () => {
      this.syncPanel();
      this.updateCollisions();
    });
  }

  // -------------------------------------------------- ポインター(配置/選択)

  private setupPointerEvents(): void {
    const dom = this.renderer.domElement;

    dom.addEventListener('pointermove', (event) => {
      if (this.activeTool && this.ghost) {
        const point = this.raycastGround(event);
        if (point) {
          this.ghost.visible = true;
          this.positionOnFloor(this.ghost, this.activeTool, point);
          this.ghost.rotation.y = this.ghostRotation;
          if (this.activeTool === 'door' || this.activeTool === 'window') {
            this.snapOpeningToWall(this.ghost);
          }
        } else {
          this.ghost.visible = false;
        }
      }
    });

    dom.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      this.pointerDown = { x: event.clientX, y: event.clientY };
    });

    dom.addEventListener('pointerup', (event) => {
      if (event.button !== 0 || !this.pointerDown) return;
      const moved = Math.hypot(
        event.clientX - this.pointerDown.x,
        event.clientY - this.pointerDown.y,
      );
      this.pointerDown = null;
      if (moved > CLICK_TOLERANCE_PX) return; // ドラッグ(視点操作)はクリック扱いしない
      if (this.transform.dragging || this.transform.axis !== null) return; // ギズモ操作中

      if (this.activeTool) {
        this.placeShape(event);
      } else {
        this.selectAt(event);
      }
    });
  }

  private pointerToNdc(event: PointerEvent): THREE.Vector2 {
    const rect = this.renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
  }

  private raycastGround(event: PointerEvent): THREE.Vector3 | null {
    this.raycaster.setFromCamera(this.pointerToNdc(event), this.activeCamera);
    const point = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(this.groundPlane, point) ? point : null;
  }

  private selectAt(event: PointerEvent): void {
    this.raycaster.setFromCamera(this.pointerToNdc(event), this.activeCamera);
    const hits = this.raycaster.intersectObjects(this.objects.children, true);
    for (const hit of hits) {
      if (!hit.object.visible) continue; // 自動非表示中の壁はクリックを透過させる
      // 当たったパーツから、objects 直下のトップレベルオブジェクトまで遡る
      let target: THREE.Object3D | null = hit.object;
      while (target && target.parent !== this.objects) {
        target = target.parent;
      }
      if (target && isCadObject(target)) {
        this.select(target);
        return;
      }
    }
    this.select(null);
  }

  // ---------------------------------------------------------------- 配置

  /** 地面クリック位置に置く。部屋の中なら床の上に載せる */
  private positionOnFloor(object: THREE.Object3D, type: PrimitiveType, point: THREE.Vector3): void {
    let y = BASE_HEIGHT[type];
    if (type !== 'room' && this.roomAt(point)) y += FLOOR_THICKNESS;
    object.position.set(this.snapValue(point.x), y, this.snapValue(point.z));
  }

  private setTool(tool: PrimitiveType | null): void {
    this.activeTool = tool;
    this.ghostRotation = 0;
    if (this.ghost) {
      this.scene.remove(this.ghost);
      for (const material of objectMaterials(this.ghost)) material.dispose();
      this.ghost = null;
    }
    document.querySelectorAll<HTMLButtonElement>('.shape-tools button').forEach((button) => {
      button.classList.toggle('active', button.dataset.shape === tool);
    });
    if (tool) {
      this.select(null);
      const ghost = createCadObject(tool, undefined, true);
      for (const material of objectMaterials(ghost)) {
        material.transparent = true;
        material.opacity = 0.45;
        material.depthWrite = false;
      }
      ghost.traverse((child) => {
        child.castShadow = false;
        child.receiveShadow = false;
      });
      ghost.visible = false;
      this.ghost = ghost;
      this.scene.add(ghost);
      this.setStatus(`${PRIMITIVE_LABELS[tool]}を配置: クリックで確定 / R で90°回転 / Esc でキャンセル`);
    }
  }

  private placeShape(event: PointerEvent): void {
    if (!this.activeTool) return;
    const point = this.raycastGround(event);
    if (!point) return;
    const type = this.activeTool;
    const object = createCadObject(type);
    this.positionOnFloor(object, type, point);
    object.rotation.y = this.ghostRotation;
    if (type === 'door' || type === 'window') {
      this.snapOpeningToWall(object);
    } else if (type !== 'room') {
      this.snapFurnitureToWalls(object);
    }
    this.history.push(this.makeAddCommand(object, `${PRIMITIVE_LABELS[type]}を追加`));
    this.setStatus(`「${object.name}」を追加しました。続けてクリックで配置 / Esc で終了`);
  }

  private rotateGhost(): void {
    if (!this.ghost) return;
    this.ghostRotation = (this.ghostRotation + Math.PI / 2) % (Math.PI * 2);
    this.ghost.rotation.y = this.ghostRotation;
  }

  // ---------------------------------------------------------------- 編集

  private deleteSelected(): void {
    if (!this.selected) return;
    const name = this.selected.name;
    this.history.push(this.makeDeleteCommand(this.selected));
    this.setStatus(`「${name}」を削除しました`);
  }

  private duplicateSelected(): void {
    if (!this.selected) return;
    const source = this.selected;
    const params = source.userData.params
      ? { ...(source.userData.params as RoomParams) }
      : undefined;
    const copy = createCadObject(
      source.userData.cadType as PrimitiveType,
      getObjectColor(source),
      false,
      params,
    );
    copy.position.copy(source.position).add(new THREE.Vector3(GRID_SNAP, 0, GRID_SNAP));
    copy.rotation.copy(source.rotation);
    copy.scale.copy(source.scale);
    this.history.push(this.makeAddCommand(copy, '複製'));
    this.setStatus(`「${source.name}」を複製しました`);
  }

  private setTransformMode(mode: 'translate' | 'rotate' | 'scale'): void {
    this.transform.setMode(mode);
    const labels = { translate: '移動', rotate: '回転', scale: '拡縮' } as const;
    (['translate', 'rotate', 'scale'] as const).forEach((m) => {
      element<HTMLButtonElement>(`mode-${m}`).classList.toggle('active', m === mode);
    });
    this.setStatus(`${labels[mode]}モード`);
  }

  // ------------------------------------------------------------ 平面図モード

  private setPlanMode(on: boolean): void {
    this.planMode = on;
    element<HTMLButtonElement>('plan-toggle').classList.toggle('active', on);
    this.orbit.enabled = !on;
    this.planOrbit.enabled = on;
    this.transform.camera = this.activeCamera;
    this.sun.castShadow = !on; // 平面図では影を落とさず室内を明るく見せる
    this.dimensions.visible = on; // 寸法線は平面図でのみ表示
    this.setStatus(on ? '平面図モード(ドラッグで移動 / ホイールで拡大縮小)' : '3D ビュー');
  }

  // ------------------------------------------------------------ 保存/読込

  private cadObjects(): THREE.Object3D[] {
    return this.objects.children.filter(isCadObject);
  }

  private proposalMeta(): ProposalMeta {
    return {
      project: element<HTMLInputElement>('proposal-project').value.trim(),
      customer: element<HTMLInputElement>('proposal-customer').value.trim(),
    };
  }

  private saveScene(): void {
    const data: SceneData = {
      format: 'web-cad',
      version: 4,
      objects: this.cadObjects().map(serializeObject),
      views: this.savedViews,
      meta: this.proposalMeta(),
    };
    downloadBlob(
      new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
      'model.json',
    );
    this.setStatus(`${data.objects.length} 個のオブジェクトを保存しました`);
  }

  private async loadScene(file: File): Promise<void> {
    try {
      const data = JSON.parse(await file.text()) as SceneData;
      if (data.format !== 'web-cad' || !Array.isArray(data.objects)) {
        throw new Error('対応していないファイル形式です');
      }
      this.select(null);
      this.setTool(null);
      this.objects.clear();
      for (const objectData of data.objects) {
        this.objects.add(deserializeObject(objectData));
      }
      this.savedViews = data.views ?? [];
      this.renderViewList();
      element<HTMLInputElement>('proposal-project').value = data.meta?.project ?? '';
      element<HTMLInputElement>('proposal-customer').value = data.meta?.customer ?? '';
      this.history.clear();
      this.setStatus(`「${file.name}」から ${data.objects.length} 個のオブジェクトを読み込みました`);
    } catch (error) {
      this.setStatus(`読み込みに失敗しました: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private exportStl(): void {
    const objects = this.cadObjects();
    if (objects.length === 0) {
      this.setStatus('エクスポートするオブジェクトがありません');
      return;
    }
    const exporter = new STLExporter();
    const result = exporter.parse(this.objects, { binary: true });
    downloadBlob(new Blob([result.buffer as ArrayBuffer], { type: 'model/stl' }), 'model.stl');
    this.setStatus(`${objects.length} 個のオブジェクトを STL に出力しました`);
  }

  // -------------------------------------------------- アングル保存と PDF

  private captureViewState(name: string): SavedViewData {
    if (this.planMode) {
      return {
        name,
        mode: 'plan',
        position: this.planCamera.position.toArray() as [number, number, number],
        target: this.planOrbit.target.toArray() as [number, number, number],
        zoom: this.planCamera.zoom,
      };
    }
    return {
      name,
      mode: 'persp',
      position: this.camera.position.toArray() as [number, number, number],
      target: this.orbit.target.toArray() as [number, number, number],
    };
  }

  private applyViewState(view: SavedViewData): void {
    this.setPlanMode(view.mode === 'plan');
    if (view.mode === 'plan') {
      this.planCamera.position.fromArray(view.position);
      this.planOrbit.target.fromArray(view.target);
      this.planCamera.zoom = view.zoom ?? 1;
      this.planCamera.updateProjectionMatrix();
      this.planOrbit.update();
    } else {
      this.camera.position.fromArray(view.position);
      this.orbit.target.fromArray(view.target);
      this.orbit.update();
    }
  }

  private addView(): void {
    const name = `アングル ${this.savedViews.length + 1}`;
    this.savedViews.push(this.captureViewState(name));
    this.renderViewList();
    this.setStatus(`「${name}」を保存しました。PDF出力で1ページずつまとめられます`);
  }

  private renderViewList(): void {
    const list = element<HTMLUListElement>('view-list');
    list.innerHTML = '';
    this.savedViews.forEach((view, index) => {
      const item = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = `${view.name}${view.mode === 'plan' ? '(平面図)' : ''}`;
      const actions = document.createElement('span');
      actions.className = 'view-actions';
      const show = document.createElement('button');
      show.textContent = '表示';
      show.addEventListener('click', () => this.applyViewState(view));
      const remove = document.createElement('button');
      remove.textContent = '削除';
      remove.addEventListener('click', () => {
        this.savedViews.splice(index, 1);
        this.renderViewList();
      });
      actions.append(show, remove);
      item.append(label, actions);
      list.appendChild(item);
    });
  }

  /** グリッドなどを隠して提案書向けの見た目に切り替える */
  private setPresentation(on: boolean): void {
    this.gridHelper.visible = !on;
    this.axesHelper.visible = !on;
    if (this.ghost) this.ghost.visible = false;
    this.scene.background = new THREE.Color(on ? BG_PRESENT : BG_EDIT);
  }

  /** 現在のキャンバスに日本語タイトル帯を付けた画像を作る */
  private captureImage(title: string): { data: string; w: number; h: number } {
    const source = this.renderer.domElement;
    const header = Math.max(48, Math.round(source.height * 0.07));
    const canvas = document.createElement('canvas');
    canvas.width = source.width;
    canvas.height = source.height + header;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#1f2933';
    ctx.font = `bold ${Math.round(header * 0.45)}px sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillText(title, Math.round(header * 0.4), header / 2);
    const date = new Date().toLocaleDateString('ja-JP');
    ctx.font = `${Math.round(header * 0.32)}px sans-serif`;
    ctx.fillStyle = '#616e7c';
    const dateWidth = ctx.measureText(date).width;
    ctx.fillText(date, canvas.width - dateWidth - Math.round(header * 0.4), header / 2);
    ctx.drawImage(source, 0, header);
    return { data: canvas.toDataURL('image/jpeg', 0.9), w: canvas.width, h: canvas.height };
  }

  /** 物件名・お客様名入りの表紙を A4 横比率のキャンバスで作る */
  private makeCoverImage(): string {
    const w = 1684;
    const h = 1190;
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d')!;
    const meta = this.proposalMeta();
    const project = meta.project || 'お部屋レイアウトのご提案';

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#2f80ed';
    ctx.fillRect(0, 0, w, 16);
    ctx.fillRect(0, h - 16, w, 16);

    ctx.fillStyle = '#616e7c';
    ctx.font = '32px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('R O O M   P L A N   P R O P O S A L', w / 2, h * 0.24);

    ctx.fillStyle = '#1f2933';
    ctx.font = 'bold 88px sans-serif';
    ctx.fillText(project, w / 2, h * 0.42);

    ctx.strokeStyle = '#2f80ed';
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(w / 2 - 180, h * 0.48);
    ctx.lineTo(w / 2 + 180, h * 0.48);
    ctx.stroke();

    if (meta.customer) {
      ctx.fillStyle = '#1f2933';
      ctx.font = '56px sans-serif';
      ctx.fillText(`${meta.customer} 様`, w / 2, h * 0.58);
    }

    ctx.fillStyle = '#616e7c';
    ctx.font = '36px sans-serif';
    ctx.fillText(`ご提案日: ${new Date().toLocaleDateString('ja-JP')}`, w / 2, h * 0.78);

    return canvas.toDataURL('image/jpeg', 0.92);
  }

  private async exportPdf(): Promise<void> {
    const views = this.savedViews.length > 0
      ? this.savedViews
      : [this.captureViewState('現在の視点')];
    this.setStatus('PDF を作成しています...');
    const { jsPDF } = await import('jspdf');
    const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
    const pageW = 297;
    const pageH = 210;

    // 1ページ目: 表紙
    doc.addImage(this.makeCoverImage(), 'JPEG', 0, 0, pageW, pageH);

    const restoreView = this.captureViewState('');
    const restoreSelected = this.selected;
    this.select(null);
    this.setPresentation(true);
    try {
      const margin = 10;
      for (const view of views) {
        this.applyViewState(view);
        this.updateWallVisibility();
        this.syncDimensions();
        this.renderer.render(this.scene, this.activeCamera);
        const image = this.captureImage(view.name);
        doc.addPage();
        const ratio = Math.min((pageW - margin * 2) / image.w, (pageH - margin * 2) / image.h);
        const w = image.w * ratio;
        const h = image.h * ratio;
        doc.addImage(image.data, 'JPEG', (pageW - w) / 2, (pageH - h) / 2, w, h);
      }
    } finally {
      this.setPresentation(false);
      this.applyViewState(restoreView);
      this.select(restoreSelected);
    }
    doc.save('room-plan.pdf');
    this.setStatus(`表紙 + ${views.length} アングルの提案書 PDF を出力しました`);
  }

  // ------------------------------------------------------------ ツールバー

  private setupToolbar(): void {
    document.querySelectorAll<HTMLButtonElement>('.shape-tools button').forEach((button) => {
      button.addEventListener('click', () => {
        const shape = button.dataset.shape as PrimitiveType;
        this.setTool(this.activeTool === shape ? null : shape);
      });
    });

    element<HTMLButtonElement>('mode-translate').addEventListener('click', () => this.setTransformMode('translate'));
    element<HTMLButtonElement>('mode-rotate').addEventListener('click', () => this.setTransformMode('rotate'));
    element<HTMLButtonElement>('mode-scale').addEventListener('click', () => this.setTransformMode('scale'));
    element<HTMLButtonElement>('plan-toggle').addEventListener('click', () => this.setPlanMode(!this.planMode));

    const snapButton = element<HTMLButtonElement>('snap-toggle');
    snapButton.addEventListener('click', () => {
      this.snapEnabled = !this.snapEnabled;
      snapButton.classList.toggle('active', this.snapEnabled);
      this.applySnapSettings();
      this.setStatus(`スナップ: ${this.snapEnabled ? 'オン' : 'オフ'}`);
    });

    element<HTMLButtonElement>('undo').addEventListener('click', () => this.history.undo());
    element<HTMLButtonElement>('redo').addEventListener('click', () => this.history.redo());
    element<HTMLButtonElement>('duplicate').addEventListener('click', () => this.duplicateSelected());
    element<HTMLButtonElement>('delete').addEventListener('click', () => this.deleteSelected());
    element<HTMLButtonElement>('save').addEventListener('click', () => this.saveScene());
    element<HTMLButtonElement>('export-stl').addEventListener('click', () => this.exportStl());
    element<HTMLButtonElement>('export-pdf').addEventListener('click', () => void this.exportPdf());
    element<HTMLButtonElement>('add-view').addEventListener('click', () => this.addView());

    const fileInput = element<HTMLInputElement>('file-input');
    element<HTMLButtonElement>('load').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      const file = fileInput.files?.[0];
      if (file) void this.loadScene(file);
      fileInput.value = '';
    });
  }

  private updateToolbarState(): void {
    element<HTMLButtonElement>('undo').disabled = !this.history.canUndo;
    element<HTMLButtonElement>('redo').disabled = !this.history.canRedo;
    element<HTMLButtonElement>('duplicate').disabled = !this.selected;
    element<HTMLButtonElement>('delete').disabled = !this.selected;
  }

  // -------------------------------------------------------- プロパティパネル

  private syncPanel(): void {
    const body = element<HTMLDivElement>('panel-body');
    const empty = element<HTMLParagraphElement>('panel-empty');
    const object = this.selected;
    body.hidden = !object;
    empty.hidden = !!object;
    if (!object) return;

    const set = (id: string, value: string) => {
      const input = element<HTMLInputElement>(id);
      if (document.activeElement !== input) input.value = value;
    };
    const round = (v: number) => String(round3(v));

    const mm = (v: number) => String(Math.round(v * 1000));

    set('prop-name', object.name);
    set('prop-px', mm(object.position.x));
    set('prop-py', mm(object.position.y));
    set('prop-pz', mm(object.position.z));
    set('prop-rx', round(THREE.MathUtils.radToDeg(object.rotation.x)));
    set('prop-ry', round(THREE.MathUtils.radToDeg(object.rotation.y)));
    set('prop-rz', round(THREE.MathUtils.radToDeg(object.rotation.z)));
    set('prop-sx', round(object.scale.x));
    set('prop-sy', round(object.scale.y));
    set('prop-sz', round(object.scale.z));
    set('prop-color', getObjectColor(object));

    const isRoom = object.userData.cadType === 'room';
    element<HTMLFieldSetElement>('room-params').hidden = !isRoom;
    if (isRoom) {
      const params = object.userData.params as RoomParams;
      set('prop-rw', mm(params.width));
      set('prop-rd', mm(params.depth));
      set('prop-rh', mm(params.height));
    }
  }

  private setupPanel(): void {
    const transformIds = [
      'prop-px', 'prop-py', 'prop-pz',
      'prop-rx', 'prop-ry', 'prop-rz',
      'prop-sx', 'prop-sy', 'prop-sz',
    ];
    for (const id of transformIds) {
      element<HTMLInputElement>(id).addEventListener('change', () => this.applyPanelTransform());
    }
    for (const id of ['prop-rw', 'prop-rd', 'prop-rh']) {
      element<HTMLInputElement>(id).addEventListener('change', () => this.applyRoomParams());
    }

    element<HTMLInputElement>('prop-name').addEventListener('change', () => {
      const object = this.selected;
      if (!object) return;
      const before = object.name;
      const after = element<HTMLInputElement>('prop-name').value.trim() || before;
      if (before === after) return;
      this.history.push({
        label: '名前変更',
        redo: () => { object.name = after; this.syncPanel(); },
        undo: () => { object.name = before; this.syncPanel(); },
      });
    });

    element<HTMLInputElement>('prop-color').addEventListener('change', () => {
      const object = this.selected;
      if (!object) return;
      const before = getObjectColor(object);
      const after = element<HTMLInputElement>('prop-color').value;
      if (before === after) return;
      this.history.push({
        label: '色変更',
        redo: () => { setObjectColor(object, after); this.syncPanel(); },
        undo: () => { setObjectColor(object, before); this.syncPanel(); },
      });
    });
  }

  private panelNumber(id: string, fallback: number): number {
    const value = Number.parseFloat(element<HTMLInputElement>(id).value);
    return Number.isFinite(value) ? value : fallback;
  }

  private applyRoomParams(): void {
    const room = this.selected;
    if (!room || room.userData.cadType !== 'room') return;
    const before = { ...(room.userData.params as RoomParams) };
    // 入力は mm、内部は m で保持する
    const after: RoomParams = {
      width: Math.max(1, this.panelNumber('prop-rw', before.width * 1000) / 1000),
      depth: Math.max(1, this.panelNumber('prop-rd', before.depth * 1000) / 1000),
      height: Math.max(0.5, this.panelNumber('prop-rh', before.height * 1000) / 1000),
    };
    if (JSON.stringify(before) === JSON.stringify(after)) return;
    this.history.push({
      label: '部屋の寸法変更',
      redo: () => { room.userData.params = { ...after }; this.updateRooms(); this.syncPanel(); },
      undo: () => { room.userData.params = { ...before }; this.updateRooms(); this.syncPanel(); },
    });
  }

  private applyPanelTransform(): void {
    const object = this.selected;
    if (!object) return;
    const before = captureTransform(object);
    // 位置の入力は mm、内部は m で保持する
    const after: TransformState = {
      position: new THREE.Vector3(
        this.panelNumber('prop-px', before.position.x * 1000) / 1000,
        this.panelNumber('prop-py', before.position.y * 1000) / 1000,
        this.panelNumber('prop-pz', before.position.z * 1000) / 1000,
      ),
      rotation: new THREE.Euler(
        THREE.MathUtils.degToRad(this.panelNumber('prop-rx', THREE.MathUtils.radToDeg(before.rotation.x))),
        THREE.MathUtils.degToRad(this.panelNumber('prop-ry', THREE.MathUtils.radToDeg(before.rotation.y))),
        THREE.MathUtils.degToRad(this.panelNumber('prop-rz', THREE.MathUtils.radToDeg(before.rotation.z))),
      ),
      scale: new THREE.Vector3(
        this.panelNumber('prop-sx', before.scale.x),
        this.panelNumber('prop-sy', before.scale.y),
        this.panelNumber('prop-sz', before.scale.z),
      ),
    };
    if (transformEquals(before, after)) return;
    this.history.push(this.makeTransformCommand(object, before, after));
  }

  // ------------------------------------------------------------ キーボード

  private setupKeyboard(): void {
    window.addEventListener('keydown', (event) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) {
        return; // 入力欄へのタイプはショートカット扱いしない
      }

      if (event.ctrlKey || event.metaKey) {
        switch (event.key.toLowerCase()) {
          case 'z':
            event.preventDefault();
            if (event.shiftKey) this.history.redo();
            else this.history.undo();
            return;
          case 'y':
            event.preventDefault();
            this.history.redo();
            return;
          case 'd':
            event.preventDefault();
            this.duplicateSelected();
            return;
        }
        return;
      }

      switch (event.key) {
        case '1':
          this.setTransformMode('translate');
          break;
        case '2':
          this.setTransformMode('rotate');
          break;
        case '3':
          this.setTransformMode('scale');
          break;
        case 'r':
        case 'R':
          if (this.activeTool) this.rotateGhost();
          break;
        case 'Delete':
        case 'Backspace':
          this.deleteSelected();
          break;
        case 'Escape':
          if (this.activeTool) this.setTool(null);
          else this.select(null);
          this.setStatus('準備完了');
          break;
      }
    });
  }
}

new CadApp();
