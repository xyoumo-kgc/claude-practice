#!/usr/bin/env python3
"""Photo enhancement pipeline for floor-coating work photos.

All tonal work happens in linear light so that exposure and local-contrast
operations do not skew hue. Gamma conversion bookends the pipeline.
"""
import numpy as np
from PIL import Image, ImageFilter, ImageOps


def to_linear(a):
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def to_srgb(a):
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


LUMA = np.array([0.2126, 0.7152, 0.0722])


def luminance(rgb):
    return rgb @ LUMA


def _box_1d(a, r, axis):
    """Moving average of width 2r+1 with edge replication, via cumsum."""
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    ap = np.pad(a, pad, mode="edge")
    cs = np.cumsum(ap, axis=axis)
    zero = np.zeros_like(np.take(cs, [0], axis=axis))
    cs = np.concatenate([zero, cs], axis=axis)
    n = a.shape[axis]
    hi = np.take(cs, range(2 * r + 1, n + 2 * r + 1), axis=axis)
    lo = np.take(cs, range(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def blur(a, sigma):
    """Gaussian blur approximated by three box passes (O(n) in sigma)."""
    if sigma < 0.5:
        return a
    w = np.sqrt(12.0 * sigma * sigma / 3.0 + 1.0)
    r = max(1, int(round((w - 1) / 2)))
    out = a
    for _ in range(3):
        out = _box_1d(out, r, 0)
        out = _box_1d(out, r, 1)
    return out


def white_balance(rgb, strength, gain_clip=(0.82, 1.28)):
    """Restrained gray-world balance.

    Gains are clipped so a scene genuinely dominated by one colour (the green
    laser shots) keeps its character instead of being neutralised flat.
    """
    if strength <= 0:
        return rgb
    means = rgb.reshape(-1, 3).mean(axis=0)
    gains = means.mean() / np.maximum(means, 1e-6)
    gains = np.clip(gains, *gain_clip)
    gains = 1.0 + (gains - 1.0) * strength
    return rgb * gains


def levels(rgb, black_pct, white_pct):
    """Stretch the tonal range using luminance percentiles."""
    y = luminance(rgb)
    lo = np.percentile(y, black_pct)
    hi = np.percentile(y, white_pct)
    if hi - lo < 1e-4:
        return rgb
    return (rgb - lo) / (hi - lo)


def tone(rgb, shadows, highlights):
    """Lift shadows and roll off highlights on a luminance mask."""
    y = np.clip(luminance(rgb), 0, 1)
    out = rgb
    if shadows:
        mask = ((1.0 - y) ** 2.2)[..., None]
        out = out + shadows * mask * (0.35 + 0.65 * out)
    if highlights:
        y2 = np.clip(luminance(out), 0, 1)
        mask = (y2 ** 3.0)[..., None]
        out = out - highlights * mask * out
    return out


def local_contrast(rgb, amount, sigma):
    """Clarity: unsharp mask on luminance only, so colours stay put."""
    if amount <= 0:
        return rgb
    y = np.clip(luminance(rgb), 1e-6, None)
    base = np.clip(blur(np.clip(y, 0, 1), sigma), 1e-6, None)
    detail = np.log(y) - np.log(base)
    scale = np.exp(detail * amount)
    return rgb * scale[..., None]


def sharpen(rgb, amount, sigma=1.1):
    if amount <= 0:
        return rgb
    y = np.clip(luminance(rgb), 0, 1)
    hi = y - blur(y, sigma)
    scale = 1.0 + amount * (hi / np.maximum(y, 0.02))
    scale = np.clip(scale, 0.75, 1.35)
    return rgb * scale[..., None]


def saturate(rgb, amount):
    if amount == 1.0:
        return rgb
    y = luminance(rgb)[..., None]
    return y + (rgb - y) * amount


def temperature(rgb, warm):
    """Positive warms (more red, less blue); negative cools."""
    if warm == 0:
        return rgb
    return rgb * np.array([1.0 + warm * 0.06, 1.0, 1.0 - warm * 0.06])


def enhance(path, out_path, *, wb=0.5, wb_clip=(0.82, 1.28), exposure=0.0,
            black_pct=0.4, white_pct=99.6, shadows=0.0, highlights=0.0,
            clarity=0.3, clarity_sigma=None, sharp=0.5, sat=1.10, warm=0.0,
            long_edge=None):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if long_edge and max(img.size) > long_edge:
        s = long_edge / max(img.size)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)

    rgb = to_linear(np.asarray(img).astype(np.float64) / 255.0)

    rgb = white_balance(rgb, wb, wb_clip)
    rgb = temperature(rgb, warm)
    rgb = rgb * (2.0 ** exposure)
    rgb = levels(rgb, black_pct, white_pct)
    rgb = tone(rgb, shadows, highlights)
    if clarity_sigma is None:
        clarity_sigma = max(img.size) / 22.0
    rgb = local_contrast(rgb, clarity, clarity_sigma)
    rgb = sharpen(rgb, sharp)
    rgb = saturate(rgb, sat)

    out = (to_srgb(rgb) * 255.0).round().astype(np.uint8)
    Image.fromarray(out).save(out_path, quality=94, subsampling=1, optimize=True)
    return out_path


# Per-photo treatment. The two laser shots are dark and heavily green-cast, so
# they get a lifted exposure and a tighter white-balance clip that trims the
# cast off the walls without draining the green glow that is the subject.
JOBS = {
    "photo1.jpg": dict(wb=0.55, black_pct=0.5, white_pct=99.5, shadows=0.08,
                       highlights=0.04, clarity=0.38, sharp=0.55, sat=1.14,
                       warm=0.15, exposure=0.05),
    "photo2.jpg": dict(wb=0.40, wb_clip=(0.88, 1.20), exposure=0.35,
                       black_pct=0.2, white_pct=99.8, shadows=0.26,
                       highlights=0.06, clarity=0.26, sharp=0.40, sat=1.04),
    "photo3.jpg": dict(wb=0.40, wb_clip=(0.88, 1.20), exposure=0.22,
                       black_pct=0.2, white_pct=99.8, shadows=0.20,
                       highlights=0.05, clarity=0.28, sharp=0.42, sat=1.04),
    "photo4.jpg": dict(wb=0.60, black_pct=0.6, white_pct=99.4, shadows=0.05,
                       highlights=0.07, clarity=0.42, sharp=0.58, sat=1.16,
                       warm=0.10),
}

if __name__ == "__main__":
    import os
    os.makedirs("edited", exist_ok=True)
    for name, params in JOBS.items():
        out = enhance(f"original/{name}", f"edited/{name.replace('.jpg', '_edited.jpg')}",
                      **params)
        print("wrote", out, os.path.getsize(out))
