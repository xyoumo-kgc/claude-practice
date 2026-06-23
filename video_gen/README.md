# 動画生成 (AI text-to-video)

テキストや画像から AI で動画を生成するためのサンプルです。

## 仕組み（全体像）

AI 動画生成には大きく 2 つの実行場所があります。

| 方法 | 必要なもの | 向いている人 |
|------|-----------|-------------|
| **クラウド API** (推奨) | API キー（多くは従量課金） | GPU を持っていない / すぐ試したい |
| **ローカルモデル** | GPU (VRAM 12GB〜)・モデルの重み | 無料で回したい / 大量生成・カスタマイズ |

このリポジトリの `generate.py` は **クラウド API** 方式で、導入が最も簡単な
[Replicate](https://replicate.com/) を既定にしています。

### 主なサービス / モデル

- **Replicate** … 1 キーで多数のモデル（MiniMax, Hunyuan, Wan など）を試せる。最初の一歩に最適。
- **fal.ai** … 高速・低レイテンシ。多くの動画モデルをホスト。
- **Runway** (Gen 系) / **Luma** (Dream Machine) / **Pika** … 高品質な商用 text/image-to-video。
- **Google Veo**（Gemini API 経由） / **OpenAI Sora API** … 大手の最新モデル。
- **ローカル**: CogVideoX, Mochi, LTX-Video, HunyuanVideo, Wan 2.1 など（要 GPU）。

## セットアップ

```bash
cd video_gen
pip install -r requirements.txt

# https://replicate.com/account/api-tokens でトークンを取得
export REPLICATE_API_TOKEN=r8_xxxxxxxx
```

## 使い方

```bash
# テキストから動画
python generate.py "a cat surfing a big wave at sunset, cinematic"

# 画像から動画 (image-to-video)
python generate.py "slow zoom in, gentle wind" --image input.jpg

# モデルを切り替える（一覧: https://replicate.com/collections/text-to-video ）
python generate.py "neon city flythrough" --model tencent/hunyuan-video

# 保存先を指定
python generate.py "a paper plane flying" --output plane.mp4
```

生成には数十秒〜数分かかります。完了すると `output.mp4`（または `--output` 指定先）に保存されます。

## 注意点

- 大半のサービスは**有料（従量課金）**です。料金は各サービスのページで確認してください。
- プロンプトは**英語**の方が品質が安定しやすいです。
- モデルは頻繁に更新・終了します。動かない場合は上記コレクションで現行モデル名を確認してください。
- 生成物の利用範囲は各サービスの利用規約に従ってください。

## ローカル（GPU）で無料で動かしたい場合

GPU があるなら Hugging Face の `diffusers` でローカル実行できます（例: CogVideoX）。
その方向で進めたい場合は教えてください。専用のスクリプトを用意します。
