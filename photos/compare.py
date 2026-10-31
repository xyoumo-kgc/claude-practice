#!/usr/bin/env python3
"""Build side-by-side before/after sheets with BEFORE / AFTER labels."""
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps

PAIRS = [(f"original/photo{i}.jpg", f"edited/photo{i}_edited.jpg", f"compare/photo{i}_compare.jpg")
         for i in range(1, 5)]
TARGET_H = 900
GAP = 16
PAD = 16
BG = (24, 24, 26)


def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def fit(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    s = TARGET_H / im.height
    return im.resize((round(im.width * s), TARGET_H), Image.LANCZOS)


def label(im, text):
    d = ImageDraw.Draw(im, "RGBA")
    f = font(max(22, im.width // 26))
    tw, th = d.textbbox((0, 0), text, font=f)[2:]
    pad = th // 2
    d.rectangle([0, 0, tw + pad * 2, th + pad * 2], fill=(0, 0, 0, 165))
    d.text((pad, pad), text, font=f, fill=(255, 255, 255))
    return im


os.makedirs("compare", exist_ok=True)
for before, after, out in PAIRS:
    a, b = label(fit(before), "BEFORE"), label(fit(after), "AFTER")
    w = PAD * 2 + a.width + GAP + b.width
    h = PAD * 2 + TARGET_H
    sheet = Image.new("RGB", (w, h), BG)
    sheet.paste(a, (PAD, PAD))
    sheet.paste(b, (PAD + a.width + GAP, PAD))
    sheet.save(out, quality=92, subsampling=1, optimize=True)
    print("wrote", out, sheet.size, os.path.getsize(out))
