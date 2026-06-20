"""Render a validated livery spec to an iRacing color TGA.

v0.1 capability: solid base fill + solid per-zone overrides. The template body is
a single flat fill color (from meta.json), so we identify that body mask once and
repaint it — splitting it between requested zones and the leftover body. Only
original body pixels are ever recolored, so baked-in decals (number board, GT3R,
PORSCHE strips) survive untouched.

Elements (stripes/logos/numbers) and materials are part of the spec contract but
are rendered in later phases (P3+/P5); the renderer reports them as warnings.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .spec import load_spec
from .tga import save_tga

# Tolerance (per channel) for matching the template's flat body fill.
BODY_MATCH_TOLERANCE = 18


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _surface_color(surface: dict) -> tuple[int, int, int]:
    """Resolve a surface's fill to an RGB tuple (v0.1: solid only)."""
    return _hex_to_rgb(surface["fill"]["color"])


def render_livery(spec: dict, template_dir: str | Path, out_path: str | Path) -> Path:
    """Render a validated v0.1 livery spec to a color TGA."""
    template_dir = Path(template_dir)
    meta = json.loads((template_dir / "meta.json").read_text())
    body_template_color = np.array(meta["body_fill_color"], np.int16)

    img = Image.open(template_dir / "base.png").convert("RGBA")
    arr = np.array(img)
    rgb = arr[..., :3].astype(np.int16)
    is_body = np.all(np.abs(rgb - body_template_color) <= BODY_MATCH_TOLERANCE, axis=-1)

    # Zone overrides first; track what they cover so the base only fills the rest.
    painted = np.zeros(is_body.shape, dtype=bool)
    zones = spec.get("zones") or {}
    if zones:
        seg = np.array(Image.open(template_dir / "zones" / "segments.png"))
        name_to_ids = json.loads(
            (template_dir / "zones" / "labels.json").read_text()
        )["zones"]
        for zone, surface in zones.items():
            ids = name_to_ids.get(zone)
            if not ids:  # validated upstream, but stay defensive
                continue
            color = _surface_color(surface)
            mask = np.isin(seg, ids) & is_body
            for c in range(3):
                arr[..., c][mask] = color[c]
            painted |= mask

    # Base fill on every remaining original-body pixel.
    base_color = _surface_color(spec["base"])
    rest = is_body & ~painted
    for c in range(3):
        arr[..., c][rest] = base_color[c]

    return save_tga(Image.fromarray(arr, "RGBA"), out_path)


def render_file(spec_path: str | Path, out_path: str | Path | None = None) -> Path:
    """Validate then render a spec file. Returns the output TGA path."""
    spec, template_dir, warnings = load_spec(spec_path)
    for w in warnings:
        print(f"  warning: {w}")
    if out_path is None:
        out_path = Path("out") / (Path(spec_path).stem + ".tga")
    return render_livery(spec, template_dir, out_path)


if __name__ == "__main__":
    import sys

    from .spec import SpecError

    spec_path = sys.argv[1] if len(sys.argv) > 1 else "liveries/example.json"
    try:
        path = render_file(spec_path)
    except SpecError as e:
        print(f"INVALID: {e}")
        raise SystemExit(1)
    print(f"rendered -> {path}")
