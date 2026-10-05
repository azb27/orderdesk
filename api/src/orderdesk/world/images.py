"""Photos of handwritten order lists: handwriting fonts on ruled paper, tilted, blurred, unevenly lit.

Some lists have a crossed-out line. The crossed-out item is not part of the truth, which tests that the
reader drops it instead of ordering it.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from orderdesk import config

FONTS = config.DATA / "fonts"
LATIN = ["Caveat.ttf", "Kalam.ttf", "PatrickHand.ttf", "IndieFlower.ttf"]
ARABIC = "ArefRuqaa.ttf"
AR_RE = re.compile(r"[؀-ۿ]")


def render_list(lines: list[str], crossed: str | None, rng: np.random.Generator, out: Path) -> None:
    latin = ImageFont.truetype(str(FONTS / LATIN[int(rng.integers(len(LATIN)))]), int(rng.integers(38, 48)))
    arabic = ImageFont.truetype(str(FONTS / ARABIC), int(rng.integers(36, 44)))
    rows = list(lines)
    cross_row = None
    if crossed:
        cross_row = int(rng.integers(0, len(rows) + 1))
        rows.insert(cross_row, crossed)
    w, step = 900, 64
    h = 110 + step * len(rows) + 60
    paper = np.array([248, 246, 236]) - rng.integers(0, 18, 3)
    img = Image.new("RGB", (w, h), tuple(int(x) for x in paper))
    d = ImageDraw.Draw(img)
    for y in range(110, h - 20, step):  # ruled lines
        d.line([(30, y + 46), (w - 30, y + 46)], fill=(170, 190, 220), width=2)
    d.line([(90, 0), (90, h)], fill=(225, 140, 140), width=2)  # margin
    ink = tuple(int(x) for x in rng.choice([[20, 30, 90], [25, 25, 30], [30, 40, 120]]))
    for i, text in enumerate(rows):
        y = 110 + i * step + int(rng.integers(-4, 5))
        is_ar = bool(AR_RE.search(text))
        font = arabic if is_ar else latin
        if is_ar:
            x = w - 60 + int(rng.integers(-10, 6))
            d.text((x, y), text, font=font, fill=ink, anchor="ra", direction="rtl")
            box = d.textbbox((x, y), text, font=font, anchor="ra", direction="rtl")
        else:
            x = 110 + int(rng.integers(0, 25))
            d.text((x, y), text, font=font, fill=ink)
            box = d.textbbox((x, y), text, font=font)
        if cross_row is not None and i == cross_row:
            mid = (box[1] + box[3]) // 2
            d.line([(box[0] - 6, mid), (box[2] + 6, mid + int(rng.integers(-6, 7)))], fill=ink, width=4)
    # camera: tilt, lighting gradient, blur, noise
    img = img.rotate(float(rng.uniform(-4, 4)), resample=Image.BICUBIC, expand=True, fillcolor=(60, 55, 50))
    arr = np.asarray(img).astype(np.float32)
    yy, xx = np.mgrid[0 : arr.shape[0], 0 : arr.shape[1]]
    angle = float(rng.uniform(0, 2 * math.pi))
    grad = (np.cos(angle) * xx / arr.shape[1] + np.sin(angle) * yy / arr.shape[0]) * float(
        rng.uniform(0.1, 0.3)
    )
    arr = arr * (1 - grad[..., None]) + rng.normal(0, 4, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(float(rng.uniform(0.2, 1.1))))
    img.thumbnail((1000, 1600))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=int(rng.integers(62, 80)))
