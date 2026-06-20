"""Render a livery to an iRacing color TGA.

Phase-0/1 renderer. Right now it supports the simplest meaningful operation:
recolor the car body to a solid color while preserving the mandatory baked-in
decals (Porsche / iRacing / GT3R, wing logos, etc.).

The body in the template is a single flat fill color, so a tolerance-based
color replace cleanly swaps the paint without touching decals. As the zone map
and livery schema land, this module grows stripes, splits, and decal placement.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .tga import save_tga

# Flat body fill color baked into the Porsche 992 template base.
TEMPLATE_BODY_COLOR = (62, 137, 205)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def recolor_body(
    base_png: str | Path,
    color,
    *,
    body_color=TEMPLATE_BODY_COLOR,
    tolerance: int = 18,
) -> Image.Image:
    """Return the base livery with the body fill swapped to `color`.

    `color` may be an (r, g, b) tuple or a "#rrggbb" string. Pixels within
    `tolerance` (per-channel) of the template body color are replaced; decals
    and trim are left untouched.
    """
    if isinstance(color, str):
        color = _hex_to_rgb(color)

    img = Image.open(base_png).convert("RGBA")
    arr = np.array(img)
    rgb = arr[..., :3].astype(np.int16)

    diff = np.abs(rgb - np.array(body_color, dtype=np.int16))
    mask = np.all(diff <= tolerance, axis=-1)

    arr[..., 0][mask] = color[0]
    arr[..., 1][mask] = color[1]
    arr[..., 2][mask] = color[2]
    return Image.fromarray(arr, "RGBA")


def render_livery(spec: dict, template_dir: str | Path, out_path: str | Path) -> Path:
    """Render a (currently minimal) livery spec to a color TGA."""
    template_dir = Path(template_dir)
    base = template_dir / "base.png"

    body = spec.get("body_color", "#1a1a1a")
    img = recolor_body(base, body)

    return save_tga(img, out_path)


if __name__ == "__main__":
    import sys

    spec_path = sys.argv[1] if len(sys.argv) > 1 else "liveries/example.json"
    spec = json.loads(Path(spec_path).read_text())
    template = Path("templates") / spec.get("template", "porsche_992_gt3")
    out = Path("out") / (Path(spec_path).stem + ".tga")
    path = render_livery(spec, template, out)
    print(f"rendered -> {path}")
