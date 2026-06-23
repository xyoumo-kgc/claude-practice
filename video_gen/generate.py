#!/usr/bin/env python3
"""テキスト（または画像）から動画を生成するサンプルスクリプト。

既定では Replicate の text-to-video モデルを使います。Replicate は
1つの API キーで多数の動画生成モデルを試せるため、最初の一歩に向いています。

使い方:
    export REPLICATE_API_TOKEN=r8_xxx           # https://replicate.com/account/api-tokens
    pip install -r requirements.txt
    python generate.py "a cat surfing a big wave at sunset, cinematic"

オプション:
    --model   使用するモデルを "owner/name" または "owner/name:version" で指定
    --image   画像から動画を作る（image-to-video）場合の入力画像パス/URL
    --output  保存先（既定: output.mp4）

モデルは頻繁に更新されるため、最新の利用可能なモデルとパラメータは
https://replicate.com/collections/text-to-video で確認してください。
例:
    --model minimax/video-01
    --model tencent/hunyuan-video
    --model wan-video/wan-2.1-t2v-480p
"""

import argparse
import os
import sys


def _require_token() -> None:
    if not os.environ.get("REPLICATE_API_TOKEN"):
        sys.exit(
            "エラー: 環境変数 REPLICATE_API_TOKEN が未設定です。\n"
            "https://replicate.com/account/api-tokens でトークンを取得し、\n"
            "  export REPLICATE_API_TOKEN=r8_xxx\n"
            "を実行してから再度お試しください。"
        )


def generate(prompt: str, model: str, image: str | None, output: str) -> str:
    """Replicate でモデルを実行し、生成された動画を output に保存して返す。"""
    import replicate  # 遅延 import: トークン未設定でも --help は動くように

    model_input: dict[str, object] = {"prompt": prompt}

    # image-to-video 系モデルは画像入力を受け取る（パラメータ名はモデル依存）。
    if image:
        file_handle = None
        if os.path.isfile(image):
            file_handle = open(image, "rb")
            model_input["image"] = file_handle
        else:
            # URL の場合はそのまま渡す
            model_input["image"] = image

    print(f"モデル '{model}' を実行中... (数十秒〜数分かかることがあります)")
    output_value = replicate.run(model, input=model_input)

    # Replicate は FileOutput / URL / リストのいずれかを返す。順に正規化する。
    file_like = output_value[0] if isinstance(output_value, list) else output_value

    with open(output, "wb") as f:
        if hasattr(file_like, "read"):            # FileOutput オブジェクト
            f.write(file_like.read())
        elif isinstance(file_like, (bytes, bytearray)):
            f.write(file_like)
        else:                                      # URL 文字列
            import requests

            resp = requests.get(str(file_like), timeout=300)
            resp.raise_for_status()
            f.write(resp.content)

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="テキスト/画像から動画を生成する（Replicate 経由）。"
    )
    parser.add_argument("prompt", help="生成したい映像の説明（英語推奨）")
    parser.add_argument(
        "--model",
        default=os.environ.get("VIDEO_MODEL", "minimax/video-01"),
        help="Replicate のモデル名（既定: minimax/video-01）",
    )
    parser.add_argument("--image", default=None, help="image-to-video 用の入力画像（パス or URL）")
    parser.add_argument("--output", default="output.mp4", help="保存先ファイル（既定: output.mp4）")
    args = parser.parse_args()

    _require_token()
    path = generate(args.prompt, args.model, args.image, args.output)
    print(f"完了: {path} を保存しました。")


if __name__ == "__main__":
    main()
