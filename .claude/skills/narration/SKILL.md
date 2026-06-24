---
name: narration
description: 施工・解説動画向けの「標準ナレーション」を生成する。標準の声は ja-JP-NanamiNeural（女性・落ち着いた声）、速度 +2%。edge-tts で音声を作る。動画にナレーションを付ける／ナレーション音声を作る／「いつもの女性の声（ナナミ）」で読み上げる、と言われたら使う。
---

# 標準ナレーション (Nanami) スキル

施工・解説動画のナレーション音声を、決まった声・速度・読み方で生成するためのスキル。

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
# 既定（Nanami / +2%）でプリセットを読み上げ
python scripts/generate_narration.py --preset presets/cupboard.json --outdir ./out
# 任意のテキスト（1行=1ファイル）
python scripts/generate_narration.py --infile lines.txt --outdir ./out
# 声・速度を変える場合
python scripts/generate_narration.py --voice ja-JP-NanamiNeural --rate +2% --infile lines.txt --outdir ./out
```

生成物は `out/0.mp3, 1.mp3, ...`。これを動画編集側で各工程に割り当てる。

## 漢字の読み方の注意（施工用語）

音声合成は施工用語を誤読しやすい。**読み上げ用テキストでは、以下を「かな」で書く**こと
（画面のテロップは漢字のままで良い）。検証は `python -c "import pyopenjtalk; print(pyopenjtalk.g2p('…', kana=True))"` で行う。

| 表記 | 誤読されやすい | 正しい読み（かなで書く） |
|------|----------------|--------------------------|
| 墨出し | ボクダシ | **すみだし** |
| 棚板 | タナバン | **たないた** |
| 下台 | シモダイ | **げだい** |
| 建て付け | タテズケ | **たてつけ** |

## カップボード施工動画のプリセット

`presets/cupboard.json` に、実映像の工程に合わせた 7 行の定型ナレーションを収録（0=導入, 1〜6=各工程）。
工程と対応テロップ:

1. 取付位置の確認・墨出し
2. キャビネット本体の設置
3. 棚板・トールキャビネットの取り付け
4. 下台・引き出しユニットの取り付け
5. 上部の固定・化粧パネルの取り付け
6. 幕板・建て付け調整・仕上げ
