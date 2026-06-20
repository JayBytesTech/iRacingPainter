"""Generate calibration skins to ground-truth the UV zone map.

Idea: paint every UV segment a distinct color and stamp its segment id on it,
then load the skin in-sim and screenshot from many angles. Cross-referencing the
visible numbers with physical panels tells us exactly which segment is which —
no guessing from the 2D unwrap.

Because 108 segments can't all carry a readable number at 2048px, we split them
into size tiers and emit one skin per tier (multi-pass). Every segment keeps the
SAME color across all passes; only the current tier gets big numbers.

Outputs (under <template>/calibration/):
  - calibration_pass{N}.tga   : color fills + this tier's numbers (load in-sim)
  - calibration_pass{N}.png   : preview
  - calibration_spec.tga      : matte spec map (no glare) — load alongside any pass
  - legend.png                : id -> color / area / centroid contact sheet

Usage:
    python -m iracing_painter.calibrate templates/porsche_992_gt3 --passes 4
"""
from __future__ import annotations

import argparse
import colorsys
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .tga import save_tga

FONT_PATH = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"


def _color_for(i: int) -> tuple[int, int, int]:
    """Stable, well-separated color per segment id (golden-ratio hue)."""
    h = (i * 0.61803398875) % 1.0
    s = 0.55 + 0.40 * ((i * 2) % 3) / 2.0     # vary saturation
    v = 0.70 + 0.30 * ((i * 5) % 2)           # vary brightness
    r, g, b = colorsys.hsv_to_rgb(h, s, min(v, 1.0))
    return int(r * 255), int(g * 255), int(b * 255)


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _text_colors(fill):
    """Black or white text (+ opposite outline) for contrast on a fill color."""
    lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return ((0, 0, 0), (255, 255, 255)) if lum > 140 else ((255, 255, 255), (0, 0, 0))


def generate(template_dir, passes: int = 4):
    template_dir = Path(template_dir)
    out_dir = template_dir / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)

    seg = np.array(Image.open(template_dir / "zones" / "segments.png")).astype(np.int32)
    records = json.loads((template_dir / "zones" / "segments.json").read_text())
    base = Image.open(template_dir / "base.png").convert("RGBA")

    # 1. Shared color fill: every segment its stable color, painted over the base.
    fill = np.array(base)
    colors = {}
    for r in records:
        c = _color_for(r["id"])
        colors[r["id"]] = c
        m = seg == r["id"]
        fill[m, 0], fill[m, 1], fill[m, 2] = c
    fill_img = Image.fromarray(fill, "RGBA")

    # 2. Tier segments by area into N passes, biggest first (pass 1 = big panels).
    by_area = sorted(records, key=lambda r: -r["area"])
    tiers = []
    chunk = max(1, len(by_area) // passes)
    for i in range(passes):
        tiers.append(by_area[i * chunk : (i + 1) * chunk] if i < passes - 1 else by_area[i * chunk :])

    # 3. One skin per tier: big numbers for that tier's segments only.
    for pi, tier in enumerate(tiers, 1):
        img = fill_img.copy()
        draw = ImageDraw.Draw(img)
        for r in tier:
            bw = r["bbox"][2] - r["bbox"][0]
            bh = r["bbox"][3] - r["bbox"][1]
            size = int(max(12, min(min(bw, bh) * 0.7, 140)))
            font = _font(size)
            label = str(r["id"])
            tcol, ocol = _text_colors(colors[r["id"]])
            x, y = r["centroid"]
            tb = draw.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            ox, oy = x - tw // 2, y - th // 2
            draw.text((ox, oy), label, font=font, fill=tcol,
                      stroke_width=max(2, size // 12), stroke_fill=ocol)
            # Underline to disambiguate mirrored digits (6 vs 9).
            uy = oy + th + max(3, size // 8)
            draw.line((ox, uy, ox + tw, uy), fill=tcol, width=max(2, size // 14))
        save_tga(img, out_dir / f"calibration_pass{pi}.tga")
        img.convert("RGB").save(out_dir / f"calibration_pass{pi}.png")

    # 4. Matte spec map: R=metallic 0, G=roughness 255, B=clearcoat 0.
    spec = np.zeros((seg.shape[0], seg.shape[1], 4), np.uint8)
    spec[..., 1] = 255   # max roughness -> matte
    spec[..., 3] = 255
    save_tga(Image.fromarray(spec, "RGBA"), out_dir / "calibration_spec.tga")

    # 5. Legend contact sheet.
    _legend(out_dir, by_area, colors)

    return out_dir, len(by_area), tiers


def _legend(out_dir, records, colors):
    cols, rowh, sw = 4, 46, 70
    rows = (len(records) + cols - 1) // cols
    W, H = cols * 360, rows * rowh + 20
    img = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(img)
    f = _font(22)
    for idx, r in enumerate(records):
        cx = (idx % cols) * 360 + 12
        cy = (idx // cols) * rowh + 12
        d.rectangle((cx, cy, cx + sw, cy + rowh - 14), fill=colors[r["id"]],
                    outline=(0, 0, 0))
        d.text((cx + sw + 12, cy + 4),
               f"#{r['id']}  a={r['area']}  ({r['centroid'][0]},{r['centroid'][1]})",
               font=f, fill=(20, 20, 20))
    img.save(out_dir / "legend.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("template", nargs="?", default="templates/porsche_992_gt3")
    ap.add_argument("--passes", type=int, default=4)
    args = ap.parse_args()
    out_dir, n, tiers = generate(args.template, passes=args.passes)
    print(f"{n} segments across {len(tiers)} passes")
    for i, t in enumerate(tiers, 1):
        ids = [r["id"] for r in t]
        print(f"  pass {i}: {len(ids)} segments  ids {ids}")
    print(f"outputs -> {out_dir}")
