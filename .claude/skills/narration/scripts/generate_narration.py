#!/usr/bin/env python3
"""標準ナレーション生成スクリプト（edge-tts）。

標準の声は ja-JP-NanamiNeural（女性・落ち着いた声）、速度 +2%。
1 行 = 1 ファイル（0.mp3, 1.mp3, ...）として出力する。

使い方:
    pip install edge-tts
    python generate_narration.py --infile lines.txt --outdir ./out
    python generate_narration.py --voice ja-JP-NanamiNeural --rate +2% --infile lines.txt --outdir ./out
    python generate_narration.py --preset lines.json --outdir ./out   # {"0": "...", "1": "..."}

注意:
    edge-tts は speech.platform.bing.com に接続する。このホストが許可された
    ネットワークでのみ動作する。403 等で失敗する環境では実行できない。

入力:
    --preset  JSON。{"0": "テキスト", "1": "テキスト", ...} 形式
    --infile  テキスト。1 行 = 1 ファイル（空行は無視）
"""
import argparse
import asyncio
import json
import os


def load_lines(args) -> dict:
    if args.preset:
        with open(args.preset, encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): v for k, v in data.items()}
    if args.infile:
        with open(args.infile, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        return dict(enumerate(lines))
    raise SystemExit("エラー: --preset か --infile のどちらかを指定してください。")


async def synth(lines: dict, voice: str, rate: str, outdir: str) -> None:
    import edge_tts

    os.makedirs(outdir, exist_ok=True)
    for i in sorted(lines):
        path = os.path.join(outdir, f"{i}.mp3")
        await edge_tts.Communicate(lines[i], voice, rate=rate).save(path)
        print(f"{path} done")
    print(f"完了: {outdir} に {len(lines)} 個の mp3 を出力しました。")


def main() -> None:
    p = argparse.ArgumentParser(description="標準ナレーション（Nanami/+2%）を生成する。")
    p.add_argument("--voice", default="ja-JP-NanamiNeural", help="既定: ja-JP-NanamiNeural")
    p.add_argument("--rate", default="+2%", help="既定: +2%%")
    p.add_argument("--preset", help="プリセット JSON ({index: text})")
    p.add_argument("--infile", help="テキスト（1 行 = 1 ファイル）")
    p.add_argument("--outdir", default="./out", help="出力先（既定: ./out）")
    args = p.parse_args()

    lines = load_lines(args)
    asyncio.run(synth(lines, args.voice, args.rate, args.outdir))


if __name__ == "__main__":
    main()
