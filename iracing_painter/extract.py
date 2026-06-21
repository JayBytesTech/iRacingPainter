"""Extract reference assets and a base color layer from a template PSD.

This is the Phase 0 plumbing: it turns the authoring PSD into the inputs the
rest of the pipeline needs:

  - reference/<layer>.png  : guide layers (UV wireframe, mask, sponsor/number
                             blocks, mandatory decals) as transparent PNGs
  - base.png               : a flattened "clean car" with all guides removed,
                             i.e. what a blank-but-valid livery looks like

Usage:
    python -m iracing_painter.extract templates/porsche_992_gt3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from psd_tools import PSDImage
from PIL import Image
from scipy import ndimage
import numpy as np


def _find_layer(psd, name):
    """Depth-first search for a layer by exact name."""
    stack = list(psd)
    while stack:
        layer = stack.pop()
        if layer.name == name:
            return layer
        if layer.is_group():
            stack.extend(list(layer))
    return None


def _layer_to_canvas(layer, size):
    """Composite a single layer onto a full-size transparent canvas."""
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    # topil() returns the layer's own raster regardless of its visibility flag,
    # which matters because several guide layers ship toggled off.
    img = layer.topil()
    if img is None:
        return canvas
    img = img.convert("RGBA")
    bbox = layer.bbox  # (x1, y1, x2, y2)
    canvas.alpha_composite(img, (bbox[0], bbox[1]))
    return canvas


def extract(template_dir: str | Path) -> None:
    template_dir = Path(template_dir)
    meta = json.loads((template_dir / "meta.json").read_text())
    size = tuple(meta["resolution"])
    ref_dir = template_dir / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)

    print(f"opening {meta['source_psd']}")
    psd = PSDImage.open(meta["source_psd"])

    # 1. Reference guide layers.
    for key, layer_name in meta["reference_layers"].items():
        if key == "comment":
            continue
        layer = _find_layer(psd, layer_name)
        if layer is None:
            print(f"  ! reference layer not found: {layer_name!r}")
            continue
        out = ref_dir / f"{key}.png"
        _layer_to_canvas(layer, size).save(out)
        print(f"  reference: {key:18s} <- {layer_name!r} -> {out.name}")

    # 2. Base color: composite ONLY the paintable group, guides excluded.
    color_group = _find_layer(psd, meta["export"]["color_group"])
    if color_group is None:
        print(f"  ! color group not found: {meta['export']['color_group']!r}")
        return
    base = color_group.composite(force=True)
    base = base.convert("RGBA")
    if base.size != size:
        fitted = Image.new("RGBA", size, (0, 0, 0, 0))
        fitted.alpha_composite(base, (0, 0))
        base = fitted
    base_out = template_dir / "base.png"
    base.save(base_out)
    print(f"  base color  -> {base_out}")

    # 3. Number blocks: detect the template's number-placement rectangles.
    detect_number_blocks(template_dir)

    # 4. Baseline spec map: composite the Custom Spec Map channel groups.
    extract_spec_base(psd, template_dir, size)

    # 5. Stock paint patterns: pull the Car Patterns group as recolor maps.
    extract_patterns(psd, template_dir, size)


def _spec_channel(group, size):
    """Composite a spec channel group (Base Paint + optional Parts) to grayscale."""
    w, h = size
    canvas = np.zeros((h, w), np.float64)
    base = parts = None
    for c in group:
        if c.name == "Base Paint":
            base = c
        elif c.name == "Parts":
            parts = c
    if base is not None:
        b = np.array(base.topil().convert("L"))
        x1, y1, x2, y2 = base.bbox
        canvas[y1:y2, x1:x2] = b[: y2 - y1, : x2 - x1]
    if parts is not None:
        pimg = parts.topil().convert("RGBA")
        pa = np.array(pimg)
        pl = np.array(pimg.convert("L"))
        alpha = pa[..., 3] / 255.0
        x1, y1, x2, y2 = parts.bbox
        region = canvas[y1:y2, x1:x2]
        canvas[y1:y2, x1:x2] = region * (1 - alpha) + pl * alpha
    return canvas.clip(0, 255).astype(np.uint8)


def extract_spec_base(psd, template_dir: str | Path, size) -> None:
    """Build the baseline spec map (parts + default body materials) -> spec_base.png.

    Channels follow the template: R=metallic, G=roughness, B=clearcoat.
    """
    template_dir = Path(template_dir)
    groups = {
        "R": _find_layer(psd, "Red Channel Metallic"),
        "G": _find_layer(psd, "Green Channel Roughness"),
        "B": _find_layer(psd, "Blue Channel Clearcoat"),
    }
    if not all(groups.values()):
        print("  ! Custom Spec Map group incomplete; skipping spec_base")
        return
    w, h = size
    spec = np.zeros((h, w, 3), np.uint8)
    for i, key in enumerate(("R", "G", "B")):
        spec[..., i] = _spec_channel(groups[key], size)
    out = template_dir / "spec_base.png"
    Image.fromarray(spec, "RGB").save(out)
    print(f"  spec base   -> {out}")


def _pattern_name(layer_name: str) -> tuple[str, str]:
    """('car_pattern_007.tga') -> ('007', 'Pattern 7'). Falls back gracefully."""
    stem = layer_name.replace(".tga", "")
    digits = "".join(ch for ch in stem if ch.isdigit())
    pid = digits or stem
    pretty = f"Pattern {int(digits)}" if digits else stem
    return pid, pretty


def extract_patterns(psd, template_dir: str | Path, size, group_name="Car Patterns") -> None:
    """Extract the stock paint patterns as recolor maps + gallery thumbnails.

    Writes templates/<t>/patterns/pattern_<id>.png (the raw R/G/B mask),
    thumbs/pattern_<id>.png (neutral-recolored preview), and manifest.json.
    Patterns are iRacing's IP (template-derived) and are gitignored, like base.png.
    """
    from .patterns import THUMB_SCHEME, is_recolorable, recolor

    template_dir = Path(template_dir)
    group = _find_layer(psd, group_name)
    if group is None:
        print(f"  ! pattern group not found: {group_name!r}; skipping patterns")
        return

    pdir = template_dir / "patterns"
    tdir = pdir / "thumbs"
    tdir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for layer in group:
        img = layer.topil()
        if img is None:
            continue
        arr = np.array(img.convert("RGB"))
        if arr.shape[:2] != (size[1], size[0]):
            canvas = np.zeros((size[1], size[0], 3), np.uint8)
            x1, y1 = layer.bbox[0], layer.bbox[1]
            canvas[y1 : y1 + arr.shape[0], x1 : x1 + arr.shape[1]] = arr[
                : size[1] - y1, : size[0] - x1
            ]
            arr = canvas
        pid, pretty = _pattern_name(layer.name)
        recolorable = is_recolorable(arr)

        Image.fromarray(arr, "RGB").save(pdir / f"pattern_{pid}.png")
        thumb_src = recolor(arr, THUMB_SCHEME) if recolorable else arr
        thumb = Image.fromarray(thumb_src, "RGB")
        thumb.thumbnail((220, 220))
        thumb.save(tdir / f"pattern_{pid}.png")

        manifest.append({"id": pid, "name": pretty, "recolor": recolorable})

    manifest.sort(key=lambda e: e["id"])
    (pdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    n_rc = sum(1 for e in manifest if e["recolor"])
    print(f"  patterns: {len(manifest)} ({n_rc} recolorable) -> patterns/manifest.json")


def detect_number_blocks(template_dir: str | Path) -> None:
    """Find number-placement rectangles from the Number Blocks guide layer.

    Writes number_blocks.json: a list of {id, bbox, rotation} where rotation is 90
    for portrait blocks (numbers read sideways in the UV) else 0. Orientation flips
    (mirroring / 180) are refined after in-sim calibration.
    """
    template_dir = Path(template_dir)
    nb_path = template_dir / "reference" / "number_blocks.png"
    if not nb_path.exists():
        print("  ! no number_blocks reference; skipping number-block detection")
        return
    a = np.array(Image.open(nb_path).convert("RGBA"))[..., 3] > 0
    labels, n = ndimage.label(a)
    blocks = []
    for i in range(1, n + 1):
        ys, xs = np.where(labels == i)
        if len(xs) < 200:
            continue
        x1, y1, x2, y2 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
        w, h = x2 - x1, y2 - y1
        blocks.append(
            {"bbox": [x1, y1, x2, y2], "rotation": 90 if h > w * 1.15 else 0}
        )
    # Stable order: top-to-bottom, then left-to-right.
    blocks.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
    for idx, b in enumerate(blocks, 1):
        b["id"] = idx
    (template_dir / "number_blocks.json").write_text(json.dumps(blocks, indent=2))
    print(f"  number blocks: {len(blocks)} -> number_blocks.json")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "templates/porsche_992_gt3"
    extract(target)
