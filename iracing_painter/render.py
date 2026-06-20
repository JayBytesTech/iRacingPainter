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
from PIL import Image, ImageDraw, ImageFont

from .spec import load_spec
from .tga import save_tga

# Tolerance (per channel) for matching the template's flat body fill.
BODY_MATCH_TOLERANCE = 18

FONT_PATH = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"


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
        resolve = _zone_resolver(template_dir)
        for target, surface in zones.items():
            ids = resolve(target)
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

    # Elements draw on top of all fills (they're decals, not body paint).
    img = Image.fromarray(arr, "RGBA")
    for el in spec.get("elements", []):
        if el.get("type") == "number":
            _draw_number(img, template_dir, el)

    return save_tga(img, out_path)


def _zone_resolver(template_dir: Path):
    """Return f(name) -> list[segment ids], resolving both zones and groups."""
    labels = json.loads((template_dir / "zones" / "labels.json").read_text())
    zone_ids = labels.get("zones", {})
    groups = labels.get("groups", {})

    def resolve(name: str):
        if name in zone_ids:
            return zone_ids[name]
        if name in groups:
            ids: list[int] = []
            for z in groups[name]:
                ids.extend(zone_ids.get(z, []))
            return ids
        return None

    return resolve


def _draw_number(img: Image.Image, template_dir: Path, el: dict) -> None:
    """Render a racing number into every template number block, fit + rotated."""
    nb_path = template_dir / "number_blocks.json"
    if not nb_path.exists():
        return
    blocks = json.loads(nb_path.read_text())
    value = el["value"]
    color = _hex_to_rgb(el.get("color", "#ffffff"))
    outline = el.get("outline")
    outline_rgb = _hex_to_rgb(outline) if outline else None

    for b in blocks:
        x1, y1, x2, y2 = b["bbox"]
        rot = b.get("rotation", 0)
        pad = 4
        # Target box in upright orientation (swap dims for rotated blocks).
        bw, bh = (x2 - x1 - 2 * pad), (y2 - y1 - 2 * pad)
        tw, th = (bh, bw) if rot in (90, 270) else (bw, bh)
        if tw <= 0 or th <= 0:
            continue
        font = _fit_font(value, tw, th)
        tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        tb = d.textbbox((0, 0), value, font=font,
                        stroke_width=max(1, font.size // 12) if outline_rgb else 0)
        txt_w, txt_h = tb[2] - tb[0], tb[3] - tb[1]
        ox = (tw - txt_w) // 2 - tb[0]
        oy = (th - txt_h) // 2 - tb[1]
        d.text((ox, oy), value, font=font, fill=(*color, 255),
               stroke_width=max(1, font.size // 12) if outline_rgb else 0,
               stroke_fill=(*outline_rgb, 255) if outline_rgb else None)
        if rot:
            tile = tile.rotate(rot, expand=True)
        img.alpha_composite(tile, (x1 + pad, y1 + pad))


def _fit_font(text: str, max_w: int, max_h: int) -> ImageFont.FreeTypeFont:
    """Largest font (by height) whose text fits within max_w x max_h."""
    probe = Image.new("RGBA", (8, 8))
    d = ImageDraw.Draw(probe)
    size = max_h
    while size > 6:
        try:
            font = ImageFont.truetype(FONT_PATH, size)
        except Exception:
            return ImageFont.load_default()
        tb = d.textbbox((0, 0), text, font=font)
        if (tb[2] - tb[0]) <= max_w and (tb[3] - tb[1]) <= max_h:
            return font
        size -= 2
    return ImageFont.truetype(FONT_PATH, 8)


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
