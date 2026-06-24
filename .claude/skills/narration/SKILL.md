---
name: narration
description: 動画やコンテンツ向けの「標準ナレーション」音声を生成する。標準の声は ja-JP-NanamiNeural（女性・落ち着いた声）、速度 +2%。edge-tts で読み上げ音声を作る。ナレーションを付ける／読み上げ音声を作る／「いつもの女性の声（ナナミ）」で読ませる、と言われたら使う。
---

# 標準ナレーション (Nanami) スキル

ナレーション音声を、決まった声・速度で生成するためのスキル。

## 標準仕様

| 項目 | 値 |
|------|----|
| エンジン | edge-tts |
| 声 | `ja-JP-NanamiNeural`（女性・落ち着いた声） |
| 速度 | `+2%`（少し速め） |
| 出力 | `0.mp3` 〜（行ごとに連番） |

## 前提（重要）

edge-tts は Microsoft の `speech.platform.bing.com` に接続する。**このホストへの通信が許可された環境でのみ生成できる。**
許可されていない環境（例: egress ポリシーで 403 になる環境）では生成段階で失敗するので、その場合は
ユーザーに「ネットワークが開いた環境でスクリプトを実行し、生成された mp3 をアップロードしてもらう」よう案内する。

## 使い方

```bash
pip install edge-tts

# テキスト（1 行 = 1 ファイル）を標準の声（Nanami / +2%）で読み上げ
python scripts/generate_narration.py --infile lines.txt --outdir ./out

# 声・速度を変える場合
python scripts/generate_narration.py --voice ja-JP-NanamiNeural --rate +2% --infile lines.txt --outdir ./out
```

生成物は `out/0.mp3, 1.mp3, ...`。

## 読み方の注意

音声合成は固有名詞や専門用語を誤読することがある。気になる語は**読み上げ用テキストで「かな」で書く**
とよい（表示するテロップは漢字のままで良い）。読みの確認は次で行える:

```bash
python -c "import pyopenjtalk; print(pyopenjtalk.g2p('確認したい文', kana=True))"
```
