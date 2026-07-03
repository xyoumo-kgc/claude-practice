# claude-practice

Claude Codeの練習用リポジトリです。

## Web CAD

ブラウザで動く自作の 3D CAD ソフトです(TypeScript + Three.js + Vite)。

![Web CAD](docs/screenshot.png)

### 起動方法

```bash
npm install
npm run dev      # 開発サーバー(http://localhost:5173)
npm run build    # 本番ビルド(dist/ に出力)
```

### 機能

- **基本図形の配置**: 立方体・球・円柱・円錐・トーラス。ツールバーで図形を選び、半透明のプレビューを見ながらクリックで配置
- **スナップ**: グリッドスナップ(0.5 単位)、回転スナップ(15°)、スケールスナップ(0.1)。ツールバーでオン/オフ切替
- **選択・編集**: クリックで選択し、ギズモで移動・回転・拡大縮小。プロパティパネルから数値・名前・色も編集可能
- **複製・削除**: Ctrl+D で複製、Delete で削除
- **Undo/Redo**: すべての操作を取り消し・やり直し可能(Ctrl+Z / Ctrl+Y)
- **保存/読込**: 独自 JSON 形式で保存・読込
- **STLエクスポート**: 3D プリントなどに使える STL(バイナリ)出力

### 操作方法

| 操作 | 内容 |
| --- | --- |
| 左ドラッグ | 視点回転 |
| 右ドラッグ | 平行移動(パン) |
| ホイール | ズーム |
| クリック | オブジェクト選択 |
| `1` / `2` / `3` | 移動 / 回転 / 拡縮モード |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+D` | 複製 |
| `Delete` | 削除 |
| `Esc` | 配置キャンセル / 選択解除 |

### 構成

```
index.html        # UI レイアウト(ツールバー・プロパティパネル)
src/main.ts       # アプリ本体(シーン・ツール・選択・入出力)
src/objects.ts    # プリミティブの生成とシリアライズ
src/history.ts    # Undo/Redo コマンドスタック
src/style.css     # スタイル
```

## 目的

- Claude Codeの使い方を学ぶ
- GitとGitHubの基本的なワークフローを練習する
- PRの作成・レビューを体験する
