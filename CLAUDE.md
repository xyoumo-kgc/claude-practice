# CLAUDE.md

このリポジトリで作業するときの前提。**内容が実態と違う場合は遠慮なく直してください。**

## このリポジトリの位置づけ

お客様への提案・制作・発信を助ける自作ツールを置く場所です。中心は **Web CAD（間取り提案ツール）** で、
そのほかに動画・SNS 発信・稼働可視化の道具が同居しています。

| ディレクトリ | 内容 | 技術 |
| --- | --- | --- |
| `src/`, `index.html` | Web CAD 本体（部屋・建具・家具・平面図・提案書 PDF・ルームツアー） | TypeScript + Three.js + Vite |
| `examples/` | サンプルシーン（JSON） | |
| `blender/` | Web CAD の JSON を読み込む Blender アドオン（パース作成） | Python（Blender 4.2+） |
| `video_gen/` | AI 動画生成のサンプル CLI（Replicate） | Python |
| `virtual-office/` | 稼働状況と Claude 使用量のダッシュボード（サーバー不要の HTML） | HTML/JS |
| `x-article-*.md` | X（旧 Twitter）記事のプロンプトテンプレと検証メモ | |
| `fusion/` | FX 融合システム FUSION-CORE の仕様・参照実装・事前登録した検証（最終検証は不合格） | Python |
| `mt5/` | MetaTrader 5 の EA（FUSION-CORE・旧 4P）と、MetaEditor なしでエンジン部を照合する道具 | MQL5 / C++ |
| `dashboard/`, `fx_*.py` | FX のダッシュボードと旧システムのバックテスト | Python（Streamlit）/ HTML |
| `.claude/skills/` | 再利用するスキル（下記） | |

## 使えるスキル

| スキル | 用途 |
| --- | --- |
| `proposal` | ヒアリング内容 → 3D シーン JSON・提案書 PDF の下地・見積内訳の下書き |
| `narration` | 標準ナレーション音声（ja-JP-NanamiNeural / +2%）の生成 |
| `fx-analyze` | FX のマルチタイムフレーム分析（4 パターン判定）※ 投資は自己責任 |
| `fx-fusion` | FX 融合システム FUSION-CORE の判定（賢人 × 100億の共通ルール）※ 最終検証は不合格。裁量の補助で、投資は自己責任 |

新しく型化したものは**必ず `.claude/skills/` に置いて `master` に入れる**こと。
機能ブランチに置いたままだと、次のセッションから呼び出せません。

## Web CAD の約束ごと

- **単位**: UI の表示・入力は **mm**。内部データと保存 JSON は **m**（既存ファイルとの互換のため変えない）。
- **保存形式**: `{ format: "web-cad", version: 4, objects, views, meta }`。旧バージョンも読めるようにする。
- 主要な定数は `src/objects.ts`（`WALL_THICKNESS = 0.12` / `FLOOR_THICKNESS = 0.05` / 建具の開口寸法）。
  シーンを生成するスクリプトを書くときはこの値に合わせる。
- 部屋は中心座標＋`params`（幅・奥行・壁高）のパラメトリック構造。壁は開口部を避けて再構築される。
- ドア・窓は壁の中心線付近に置くと吸着する。境界壁に置くと**両側の壁に穴が開いて部屋がつながる**。

## 開発コマンド

```bash
npm install
npm run dev           # 開発サーバー(http://localhost:5173)
npm run build         # 型チェック + ビルド
npm run build:single  # 配布用の単一 HTML(dist-single/index.html)

npm run typecheck     # 本体 + テストコードの型チェック
npm run test:skills   # proposal スキル(シーン生成・見積)の検証
npm run test:e2e      # Playwright E2E(先に npm run build が必要)
npm test              # スキル検証 + E2E
```

変更したら **`npm run build` と `npm test` が通ること**を確認する。同じ内容が CI
（`.github/workflows/ci.yml`）で PR ごとに自動実行される。
E2E は `tests/e2e/`、スキルの検証は `tests/skills/`。画面の挙動を変えたら、
対応するテストを足すか更新して、確認結果を PR に書く。

### FX ツール（`fusion/`・`mt5/`）

```bash
python3 -m unittest discover -s fusion/tests -t .                  # 参照実装・照合ハーネス・評価スクリプトのテスト
FUSION_DATA_DIR=<H1 足のフォルダ> bash mt5/engine_check/run.sh quick  # EA のエンジン部と Python の照合（g++ が必要）
```

- `fusion/SPEC.md` は凍結。判定を変える改良は v1.1 として事前登録し（`fusion/PREREGISTRATION.md` と同じ手順）、新しい未接触データで1回だけ評価する。
- 相場データ（1分足・H1 足の CSV）はコミットしない。入手と変換の手順は `fusion/README.md` にある。

## 進め方

- **1 PR = 1 目的**。作業ブランチは `claude/<内容>`。
- PR 本文は日本語で、「概要 / 変更点 / 動作確認」を書く。スクリーンショットがあると伝わる。
- 大きめの改修は先に方針を出して合意してから実装する。
- **このリポジトリは公開（public）です。** 見積システム（みつも郎）の本体・商品マスタ（原価・割引率）・口座番号・社員名・お客様の情報はコミットしない。社内向けの成果物はファイルで直接渡す。
- お客様の氏名・住所・金額などが入るファイルはコミットしない（`work/` は .gitignore 済み）。
- API キー・トークンは環境変数で渡す。ファイルに書かない。

## 文体

- ドキュメント・コメント・PR・コミットメッセージは**日本語**。
- コード中のコメントは「なぜそうしたか」を簡潔に。既存コードの密度に合わせる。
