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


def paint_zones(
    img: Image.Image,
    template_dir: str | Path,
    zone_colors: dict,
    *,
    body_color=TEMPLATE_BODY_COLOR,
    tolerance: int = 18,
) -> Image.Image:
    """Recolor individual UV zones by name.

    `zone_colors` maps a semantic zone name (from zones/labels.json) to a color.
    Only pixels inside the zone that still match the template body fill are
    repainted, so baked-in decals (number board, GT3R, PORSCHE strips) survive.
    """
    template_dir = Path(template_dir)
    seg = np.array(Image.open(template_dir / "zones" / "segments.png"))
    labels = json.loads((template_dir / "zones" / "labels.json").read_text())
    name_to_ids = labels["zones"]

    arr = np.array(img.convert("RGBA"))
    rgb = arr[..., :3].astype(np.int16)
    is_body = np.all(np.abs(rgb - np.array(body_color, np.int16)) <= tolerance, axis=-1)

    for zone, color in zone_colors.items():
        ids = name_to_ids.get(zone)
        if not ids:
            print(f"  ! unknown zone {zone!r} (not in labels.json)")
            continue
        if isinstance(color, str):
            color = _hex_to_rgb(color)
        zone_mask = np.isin(seg, ids) & is_body
        for c in range(3):
            arr[..., c][zone_mask] = color[c]
    return Image.fromarray(arr, "RGBA")


def render_livery(spec: dict, template_dir: str | Path, out_path: str | Path) -> Path:
    """Render a livery spec to a color TGA.

    Spec keys (v0):
      body_color : base color for the whole car
      zones      : {zone_name: color} overrides for specific UV zones

    The body fill is identified once from the template, then split between the
    requested zones and the leftover body. Only original body pixels are ever
    repainted, so all baked-in decals survive.
    """
    template_dir = Path(template_dir)

    img = Image.open(template_dir / "base.png").convert("RGBA")
    arr = np.array(img)
    rgb = arr[..., :3].astype(np.int16)
    is_body = np.all(
        np.abs(rgb - np.array(TEMPLATE_BODY_COLOR, np.int16)) <= 18, axis=-1
    )

    zones = spec.get("zones") or {}
    painted = np.zeros(is_body.shape, dtype=bool)
    if zones:
        seg = np.array(Image.open(template_dir / "zones" / "segments.png"))
        name_to_ids = json.loads(
            (template_dir / "zones" / "labels.json").read_text()
        )["zones"]
        for zone, color in zones.items():
            ids = name_to_ids.get(zone)
            if not ids:
                print(f"  ! unknown zone {zone!r} (not in labels.json)")
                continue
            color = _hex_to_rgb(color) if isinstance(color, str) else color
            mask = np.isin(seg, ids) & is_body
            for c in range(3):
                arr[..., c][mask] = color[c]
            painted |= mask

    # Everything still on the original body color gets the base body color.
    body = spec.get("body_color", "#1a1a1a")
    body = _hex_to_rgb(body) if isinstance(body, str) else body
    rest = is_body & ~painted
    for c in range(3):
        arr[..., c][rest] = body[c]

    return save_tga(Image.fromarray(arr, "RGBA"), out_path)


if __name__ == "__main__":
    import sys

    spec_path = sys.argv[1] if len(sys.argv) > 1 else "liveries/example.json"
    spec = json.loads(Path(spec_path).read_text())
    template = Path("templates") / spec.get("template", "porsche_992_gt3")
    out = Path("out") / (Path(spec_path).stem + ".tga")
    path = render_livery(spec, template, out)
    print(f"rendered -> {path}")
