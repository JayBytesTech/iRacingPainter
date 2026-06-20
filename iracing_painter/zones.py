"""Build a zone map from a template's UV wireframe.

The wireframe (`reference/uv_wireframe.png`) draws panel boundaries as pure-green
lines (`[1,255,0]`) over the mesh. We treat those green lines as walls, flood the
background in from the canvas border, and whatever stays enclosed is a panel
region. Each region gets an integer id; a JSON sidecar records area / centroid /
bbox, and a numbered preview lets a human assign names.

Outputs (under <template>/zones/):
  - segments.png        : indexed PNG, pixel value = region id (0 = background)
  - segments_preview.png: random-colored regions with id numbers, over the base
  - segments.json       : [{id, area, centroid:[x,y], bbox:[x1,y1,x2,y2]}, ...]

Usage:
    python -m iracing_painter.zones templates/porsche_992_gt3 [--min-area 600]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage


GREEN = "green boundary lines, pure [1,255,0]"


def _green_mask(wire: np.ndarray) -> np.ndarray:
    r, g, b, a = (wire[..., i].astype(int) for i in range(4))
    return (a > 0) & (g > 80) & (g > r + 25) & (g > b + 25)


def segment(template_dir: str | Path, min_area: int = 600, wall_dilate: int = 2):
    template_dir = Path(template_dir)
    wire = np.array(
        Image.open(template_dir / "reference" / "uv_wireframe.png").convert("RGBA")
    )
    h, w = wire.shape[:2]

    # Walls = green panel boundaries, thickened to close 1px gaps.
    walls = _green_mask(wire)
    if wall_dilate:
        walls = ndimage.binary_dilation(walls, iterations=wall_dilate)

    # Flood the background in from the border through everything that isn't a wall.
    free = ~walls
    # Label connected free-space; the component(s) touching the border are background.
    labels, n = ndimage.label(free)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(
        labels[:, -1]
    )
    border.discard(0)

    # Candidate regions = free components not connected to the border.
    seg = np.zeros((h, w), dtype=np.int32)
    records = []
    next_id = 1
    for comp in range(1, n + 1):
        if comp in border:
            continue
        comp_mask = labels == comp
        area = int(comp_mask.sum())
        if area < min_area:
            continue
        ys, xs = np.where(comp_mask)
        seg[comp_mask] = next_id
        records.append(
            {
                "id": next_id,
                "area": area,
                "centroid": [int(xs.mean()), int(ys.mean())],
                "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                "name": None,
            }
        )
        next_id += 1

    records.sort(key=lambda r: -r["area"])
    return seg, records


def write_outputs(template_dir, seg, records):
    template_dir = Path(template_dir)
    out_dir = template_dir / "zones"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Indexed segment map (id per pixel).
    Image.fromarray(seg.astype(np.uint16)).save(out_dir / "segments.png")
    (out_dir / "segments.json").write_text(json.dumps(records, indent=2))

    # Colored preview over the base, with id numbers at centroids.
    rng = np.random.default_rng(7)
    palette = {r["id"]: rng.integers(40, 230, size=3) for r in records}
    base = Image.open(template_dir / "base.png").convert("RGBA")
    overlay = np.array(base).copy()
    for r in records:
        m = seg == r["id"]
        col = palette[r["id"]]
        overlay[m, 0] = (overlay[m, 0] * 0.25 + col[0] * 0.75).astype(np.uint8)
        overlay[m, 1] = (overlay[m, 1] * 0.25 + col[1] * 0.75).astype(np.uint8)
        overlay[m, 2] = (overlay[m, 2] * 0.25 + col[2] * 0.75).astype(np.uint8)
    prev = Image.fromarray(overlay, "RGBA")
    draw = ImageDraw.Draw(prev)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 34
        )
    except Exception:
        font = ImageFont.load_default()
    for r in records:
        x, y = r["centroid"]
        label = str(r["id"])
        draw.text((x - 10, y - 16), label, fill=(255, 255, 0), font=font,
                  stroke_width=3, stroke_fill=(0, 0, 0))
    prev.convert("RGB").save(out_dir / "segments_preview.png")
    return out_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("template", nargs="?", default="templates/porsche_992_gt3")
    ap.add_argument("--min-area", type=int, default=600)
    args = ap.parse_args()
    seg, records = segment(args.template, min_area=args.min_area)
    out_dir = write_outputs(args.template, seg, records)
    print(f"found {len(records)} regions >= {args.min_area}px")
    for r in records[:25]:
        print(f"  id {r['id']:>3}  area {r['area']:>8}  centroid {tuple(r['centroid'])}")
    print(f"outputs -> {out_dir}")
