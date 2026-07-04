import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js';
import { History, type Command } from './history';
import {
  BASE_HEIGHT,
  PRIMITIVE_LABELS,
  createCadObject,
  deserializeObject,
  getObjectColor,
  isCadObject,
  objectMaterials,
  serializeObject,
  setObjectColor,
  type PrimitiveType,
  type SceneData,
} from './objects';
import './style.css';

const GRID_SNAP = 0.5;
const ROTATION_SNAP = THREE.MathUtils.degToRad(15);
const SCALE_SNAP = 0.1;
const CLICK_TOLERANCE_PX = 5;

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

class CadApp {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly orbit: OrbitControls;
  private readonly transform: TransformControls;
  private readonly raycaster = new THREE.Raycaster();
  private readonly groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  /** ユーザーが作成した CAD オブジェクトだけを入れるグループ */
  private readonly objects = new THREE.Group();
  private readonly history = new History();

  private readonly viewport = element<HTMLDivElement>('viewport');
  private readonly statusBar = element<HTMLElement>('status');

  private activeTool: PrimitiveType | null = null;
  private ghost: THREE.Object3D | null = null;
  private ghostRotation = 0;
  private selected: THREE.Object3D | null = null;
  private snapEnabled = true;
  private dragStartState: TransformState | null = null;
  private pointerDown: { x: number; y: number } | null = null;

  constructor() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.viewport.appendChild(this.renderer.domElement);

    this.scene.background = new THREE.Color('#22242a');
    this.scene.add(this.objects);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 500);
    this.camera.position.set(7, 6, 9);

    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.target.set(0, 0.5, 0);
    this.orbit.enableDamping = true;

    this.transform = new TransformControls(this.camera, this.renderer.domElement);
    this.scene.add(this.transform.getHelper());

    this.setupEnvironment();
    this.setupTransformEvents();
    this.setupPointerEvents();
    this.setupToolbar();
    this.setupPanel();
    this.setupKeyboard();
    this.applySnapSettings();

    this.history.onChange = () => this.updateToolbarState();
    this.updateToolbarState();

    window.addEventListener('resize', () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop(() => {
      this.orbit.update();
      this.renderer.render(this.scene, this.camera);
    });

    this.setStatus('準備完了。「部屋」を置いてから家具を配置してみてください。');
  }

  // ---------------------------------------------------------------- 環境

  private setupEnvironment(): void {
    const hemisphere = new THREE.HemisphereLight('#cfd8e6', '#3a3f4a', 0.9);
    this.scene.add(hemisphere);

    const sun = new THREE.DirectionalLight('#ffffff', 1.6);
    sun.position.set(8, 14, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -20;
    sun.shadow.camera.right = 20;
    sun.shadow.camera.top = 20;
    sun.shadow.camera.bottom = -20;
    this.scene.add(sun);

    const grid = new THREE.GridHelper(40, 80, '#5a6070', '#33363f');
    this.scene.add(grid);
    this.scene.add(new THREE.AxesHelper(2.5));

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
    this.camera.aspect = clientWidth / Math.max(clientHeight, 1);
    this.camera.updateProjectionMatrix();
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

  // ---------------------------------------------------------------- 選択

  private setHighlight(object: THREE.Object3D, on: boolean): void {
    for (const material of objectMaterials(object)) {
      material.emissive.setHex(on ? 0x1a4d99 : 0x000000);
    }
  }

  private select(object: THREE.Object3D | null): void {
    if (this.selected === object) return;
    if (this.selected) this.setHighlight(this.selected, false);
    this.selected = object;
    if (object) {
      this.setHighlight(object, true);
      this.transform.attach(object);
      this.setStatus(`「${object.name}」を選択中`);
    } else {
      this.transform.detach();
    }
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
      this.orbit.enabled = !event.value;
    });
    this.transform.addEventListener('mouseDown', () => {
      if (this.selected) this.dragStartState = captureTransform(this.selected);
    });
    this.transform.addEventListener('mouseUp', () => {
      if (!this.selected || !this.dragStartState) return;
      const after = captureTransform(this.selected);
      if (!transformEquals(this.dragStartState, after)) {
        // 変形はドラッグ中に適用済みなので execute=false で履歴にだけ積む
        this.history.push(this.makeTransformCommand(this.selected, this.dragStartState, after), false);
      }
      this.dragStartState = null;
    });
    this.transform.addEventListener('objectChange', () => this.syncPanel());
  }

  // -------------------------------------------------- ポインター(配置/選択)

  private setupPointerEvents(): void {
    const dom = this.renderer.domElement;

    dom.addEventListener('pointermove', (event) => {
      if (this.activeTool && this.ghost) {
        const point = this.raycastGround(event);
        if (point) {
          this.ghost.visible = true;
          this.ghost.position.set(
            this.snapValue(point.x),
            BASE_HEIGHT[this.activeTool],
            this.snapValue(point.z),
          );
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
    this.raycaster.setFromCamera(this.pointerToNdc(event), this.camera);
    const point = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(this.groundPlane, point) ? point : null;
  }

  private selectAt(event: PointerEvent): void {
    this.raycaster.setFromCamera(this.pointerToNdc(event), this.camera);
    const hits = this.raycaster.intersectObjects(this.objects.children, true);
    for (const hit of hits) {
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
    object.position.set(this.snapValue(point.x), BASE_HEIGHT[type], this.snapValue(point.z));
    object.rotation.y = this.ghostRotation;
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
    const copy = createCadObject(source.userData.cadType as PrimitiveType, getObjectColor(source));
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

  // ------------------------------------------------------------ 保存/読込

  private cadObjects(): THREE.Object3D[] {
    return this.objects.children.filter(isCadObject);
  }

  private saveScene(): void {
    const data: SceneData = {
      format: 'web-cad',
      version: 2,
      objects: this.cadObjects().map(serializeObject),
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
    const round = (v: number) => String(Math.round(v * 1000) / 1000);

    set('prop-name', object.name);
    set('prop-px', round(object.position.x));
    set('prop-py', round(object.position.y));
    set('prop-pz', round(object.position.z));
    set('prop-rx', round(THREE.MathUtils.radToDeg(object.rotation.x)));
    set('prop-ry', round(THREE.MathUtils.radToDeg(object.rotation.y)));
    set('prop-rz', round(THREE.MathUtils.radToDeg(object.rotation.z)));
    set('prop-sx', round(object.scale.x));
    set('prop-sy', round(object.scale.y));
    set('prop-sz', round(object.scale.z));
    set('prop-color', getObjectColor(object));
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

  private applyPanelTransform(): void {
    const object = this.selected;
    if (!object) return;
    const num = (id: string, fallback: number) => {
      const value = Number.parseFloat(element<HTMLInputElement>(id).value);
      return Number.isFinite(value) ? value : fallback;
    };
    const before = captureTransform(object);
    const after: TransformState = {
      position: new THREE.Vector3(
        num('prop-px', before.position.x),
        num('prop-py', before.position.y),
        num('prop-pz', before.position.z),
      ),
      rotation: new THREE.Euler(
        THREE.MathUtils.degToRad(num('prop-rx', THREE.MathUtils.radToDeg(before.rotation.x))),
        THREE.MathUtils.degToRad(num('prop-ry', THREE.MathUtils.radToDeg(before.rotation.y))),
        THREE.MathUtils.degToRad(num('prop-rz', THREE.MathUtils.radToDeg(before.rotation.z))),
      ),
      scale: new THREE.Vector3(
        num('prop-sx', before.scale.x),
        num('prop-sy', before.scale.y),
        num('prop-sz', before.scale.z),
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
