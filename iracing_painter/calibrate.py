"""Generate a calibration livery to ground-truth the UV map from in-sim shots.

Two color passes (share one matte spec map), each answering different questions
when applied in-sim and photographed/filmed from every angle:

1. segid  — every UV segment filled with a distinct color and stamped with its
            segment id. The number is drawn upright in UV with an underline (marks
            UV-"down") and a cyan tick at the upright top-left (marks the UV origin
            corner). Reading the number tells you which segment is which physical
            panel; the underline/tick orientation tells you how that UV island is
            rotated/mirrored on the car. -> verify & fill in labels.json, detect
            mirroring/rotation.

2. uv_grid — a UV coordinate gradient: R = x position, G = y position (B = 128),
            with black reference grid lines every 64 px (thin) and 256 px (bold).
            Any pixel's colour decodes to its UV coordinate, so a screenshot gives
            a dense UV<->3D correspondence: sample both sides of a physical seam to
            read the two UV coords that meet there (closes the seam graph car-wide),
            and the wrapped grid reveals the 3D shape/curvature. -> position map,
            seams for roof/doors/rear, rough 3D.

Outputs (under <template>/calibration/): segid.tga, uv_grid.tga, spec_matte.tga,
plus *_preview.png, legend.png, and decode_key.json (the formulas + per-segment
palette/centroid/label so the shots can be decoded later, deterministically).

Apply in-sim as car_<custID>.tga (+ car_spec_<custID>.tga = spec_matte) one pass at
a time; see docs/CALIBRATION.md for the capture protocol.

Usage:
    python -m iracing_painter.calibrate templates/porsche_992_gt3
"""
from __future__ import annotations

import argparse
import colorsys
import datetime as _dt
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .fonts import load_font
from .tga import save_tga

TICK_COLOR = (0, 255, 255)   # cyan UV-origin marker (fixed, so it's findable)
GRID_THIN = 64
GRID_BOLD = 256
NUMERAL_MIN_AREA = 1500      # only stamp a number on segments big enough to read
NUMERAL_MIN_SIDE = 26        # ...and with a bbox that can fit a glyph


def _color_for(i: int) -> tuple[int, int, int]:
    """Stable, well-separated color per segment id (golden-ratio hue + varied S/V)."""
    h = (i * 0.61803398875) % 1.0
    s = 0.65 + 0.30 * ((i * 0.37) % 1.0)
    v = 0.72 + 0.28 * ((i * 0.53) % 1.0)
    r, g, b = colorsys.hsv_to_rgb(h, s, min(v, 1.0))
    return int(r * 255), int(g * 255), int(b * 255)


def _text_colors(fill):
    """(text, outline) — black-on-light or white-on-dark for contrast."""
    lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return ((0, 0, 0), (255, 255, 255)) if lum > 140 else ((255, 255, 255), (0, 0, 0))


def _seg_records(template_dir: Path):
    """Per-segment {id, area, centroid, bbox} from segments.png."""
    seg = np.array(Image.open(template_dir / "zones" / "segments.png")).astype(np.int32)
    recs = []
    for sid in np.unique(seg):
        if sid == 0:
            continue
        ys, xs = np.where(seg == sid)
        recs.append({
            "id": int(sid),
            "area": int(len(xs)),
            "centroid": [int(xs.mean()), int(ys.mean())],
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        })
    return seg, recs


def _make_segid(seg, recs, colors) -> Image.Image:
    """Distinct color per segment + an upright, underlined, tick-marked numeral."""
    h, w = seg.shape
    arr = np.full((h, w, 3), 28, np.uint8)  # segment 0 / background = dark grey
    for r in recs:
        arr[seg == r["id"]] = colors[r["id"]]
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    draw = ImageDraw.Draw(img)
    for r in recs:
        x1, y1, x2, y2 = r["bbox"]
        bw, bh = x2 - x1, y2 - y1
        if r["area"] < NUMERAL_MIN_AREA or min(bw, bh) < NUMERAL_MIN_SIDE:
            continue
        size = int(max(14, min(min(bw, bh) * 0.6, 130)))
        font = load_font(size)
        label = str(r["id"])
        tcol, ocol = _text_colors(colors[r["id"]])
        cx, cy = r["centroid"]
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ox, oy = cx - tw // 2 - tb[0], cy - th // 2 - tb[1]
        sw = max(2, size // 12)
        draw.text((ox, oy), label, font=font, fill=tcol, stroke_width=sw, stroke_fill=ocol)
        # Underline marks UV-"down"; cyan tick marks the upright top-left (UV origin).
        uy = cy + th // 2 + max(3, size // 8)
        draw.line((cx - tw // 2, uy, cx + tw // 2, uy), fill=tcol, width=max(2, size // 14))
        t = max(6, size // 8)
        tlx, tly = cx - tw // 2 - t, cy - th // 2 - t
        draw.rectangle((tlx, tly, tlx + t, tly + t), fill=TICK_COLOR)
    return img


def _make_uv_grid(h, w) -> Image.Image:
    """R = x, G = y gradient (B=128) + thin/bold reference grid lines."""
    yy, xx = np.mgrid[0:h, 0:w]
    arr = np.zeros((h, w, 3), np.uint8)
    arr[..., 0] = np.round(xx / (w - 1) * 255).astype(np.uint8)
    arr[..., 1] = np.round(yy / (h - 1) * 255).astype(np.uint8)
    arr[..., 2] = 128
    img = Image.fromarray(arr, "RGB").convert("RGBA")
    draw = ImageDraw.Draw(img)
    for x in range(0, w, GRID_THIN):
        draw.line((x, 0, x, h), fill=(20, 20, 20), width=1)
    for y in range(0, h, GRID_THIN):
        draw.line((0, y, w, y), fill=(20, 20, 20), width=1)
    for x in range(0, w, GRID_BOLD):
        draw.line((x, 0, x, h), fill=(0, 0, 0), width=3)
    for y in range(0, h, GRID_BOLD):
        draw.line((0, y, w, y), fill=(0, 0, 0), width=3)
    return img


def _legend(out_dir: Path, recs, colors, labels):
    cols, rowh, sw = 3, 44, 64
    shown = [r for r in recs if r["area"] >= 600]
    rows = (len(shown) + cols - 1) // cols
    W, H = cols * 420, rows * rowh + 20
    img = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(img)
    f = load_font(20)
    for idx, r in enumerate(sorted(shown, key=lambda r: -r["area"])):
        cx = (idx % cols) * 420 + 12
        cy = (idx // cols) * rowh + 12
        d.rectangle((cx, cy, cx + sw, cy + rowh - 14), fill=colors[r["id"]], outline=(0, 0, 0))
        lab = labels.get(r["id"], "?")
        d.text((cx + sw + 10, cy + 4), f"#{r['id']}  {lab}  a={r['area']}", font=f, fill=(20, 20, 20))
    img.save(out_dir / "legend.png")


def generate(template_dir):
    template_dir = Path(template_dir)
    out_dir = template_dir / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)

    seg, recs = _seg_records(template_dir)
    h, w = seg.shape
    colors = {r["id"]: _color_for(r["id"]) for r in recs}

    # segment id -> label (from current labels.json), for the legend + decode key.
    labels: dict[int, str] = {}
    lpath = template_dir / "zones" / "labels.json"
    labels_doc = {}
    if lpath.exists():
        labels_doc = json.loads(lpath.read_text())
        for zone, ids in labels_doc.get("zones", {}).items():
            for sid in ids:
                labels[sid] = zone

    segid = _make_segid(seg, recs, colors)
    save_tga(segid, out_dir / "segid.tga")
    segid.convert("RGB").resize((900, 900)).save(out_dir / "segid_preview.png")

    uv = _make_uv_grid(h, w)
    save_tga(uv, out_dir / "uv_grid.tga")
    uv.convert("RGB").resize((900, 900)).save(out_dir / "uv_grid_preview.png")

    spec = Image.fromarray(
        np.dstack([np.zeros((h, w), np.uint8), np.full((h, w), 255, np.uint8),
                   np.zeros((h, w), np.uint8)]), "RGB")
    save_tga(spec, out_dir / "spec_matte.tga", bits=24)

    _legend(out_dir, recs, colors, labels)

    key = {
        "template": template_dir.name,
        "resolution": [w, h],
        "generated": _dt.date.today().isoformat(),
        "passes": {
            "segid": {
                "file": "segid.tga",
                "decode": "Each UV segment is one palette colour with its segment id "
                          "printed upright in UV. Read the number = segment id. The "
                          "underline sits on the UV-'down' edge; the cyan square tick "
                          "is at the upright top-left (UV origin). Their orientation in "
                          "a screenshot reveals how that UV island is rotated/mirrored "
                          "on the car. Use to verify/fill labels.json + detect mirroring.",
                "palette": {str(r["id"]): list(colors[r["id"]]) for r in recs},
                "tick_color": list(TICK_COLOR),
            },
            "uv_grid": {
                "file": "uv_grid.tga",
                "decode": "Pixel colour -> UV coordinate: x = round(R/255*(W-1)), "
                          "y = round(G/255*(H-1)); B=128 is constant. Black grid lines "
                          "every 64 px (thin) and 256 px (bold) are anchored references "
                          "(re-establish absolute UV under shading). At any physical "
                          "seam, sample the colour on each side to recover the two UV "
                          "coords that meet -> add to zones/seams.json (closes roof/"
                          "doors/rear). The wrapped grid shows 3D shape/curvature.",
                "grid_thin_px": GRID_THIN,
                "grid_bold_px": GRID_BOLD,
            },
            "spec": {
                "file": "spec_matte.tga",
                "note": "Matte (metallic 0, roughness 255, clearcoat 0). Apply as "
                        "car_spec_<custID>.tga with EITHER colour pass to kill glare.",
            },
        },
        "segments": [
            {**r, "color": list(colors[r["id"]]),
             "label": labels.get(r["id"]), "has_numeral": r["area"] >= NUMERAL_MIN_AREA
             and min(r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]) >= NUMERAL_MIN_SIDE}
            for r in sorted(recs, key=lambda r: -r["area"])
        ],
        "open_questions": labels_doc.get("_needs_insim", {}),
        "current_labels": labels_doc.get("zones", {}),
    }
    (out_dir / "decode_key.json").write_text(json.dumps(key, indent=2))
    return out_dir, len(recs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("template", nargs="?", default="templates/porsche_992_gt3")
    args = ap.parse_args()
    out_dir, n = generate(args.template)
    print(f"calibration livery for {n} segments -> {out_dir}")
    for f in ["segid.tga", "uv_grid.tga", "spec_matte.tga", "decode_key.json", "legend.png"]:
        print(f"  {f}")
