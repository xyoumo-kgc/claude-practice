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
    --video   既存動画を作り変える（video-to-video）場合の入力動画パス/URL
    --output  保存先（既定: output.mp4）

video-to-video（既存動画にエフェクト/動きを変える）の例:
    # video-to-video 対応モデルを指定し、--video に元動画を渡す
    python generate.py "make it look like a watercolor painting" \
        --video clip.mp4 --model <video-to-video モデル>
    対応モデルは https://replicate.com/collections/video-to-video で確認。

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


def generate(
    prompt: str,
    model: str,
    output: str,
    image: str | None = None,
    video: str | None = None,
) -> str:
    """Replicate でモデルを実行し、生成された動画を output に保存して返す。"""
    import replicate  # 遅延 import: トークン未設定でも --help は動くように

    model_input: dict[str, object] = {"prompt": prompt}
    open_files: list = []

    def attach(key: str, source: str) -> None:
        """ローカルパスならファイルを開いて渡し、それ以外は URL としてそのまま渡す。"""
        if os.path.isfile(source):
            fh = open(source, "rb")
            open_files.append(fh)
            model_input[key] = fh
        else:
            model_input[key] = source

    # image-to-video 系は画像入力、video-to-video 系は動画入力を受け取る
    # （パラメータ名はモデル依存。"image" / "video" が一般的）。
    if image:
        attach("image", image)
    if video:
        attach("video", video)

    print(f"モデル '{model}' を実行中... (数十秒〜数分かかることがあります)")
    try:
        output_value = replicate.run(model, input=model_input)
    finally:
        for fh in open_files:
            fh.close()

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
    parser.add_argument("--video", default=None, help="video-to-video 用の入力動画（パス or URL）")
    parser.add_argument("--output", default="output.mp4", help="保存先ファイル（既定: output.mp4）")
    args = parser.parse_args()

    _require_token()
    path = generate(args.prompt, args.model, args.output, image=args.image, video=args.video)
    print(f"完了: {path} を保存しました。")


if __name__ == "__main__":
    main()
