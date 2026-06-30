"""Procedural glitch / shatter shard fields -> transparent PNG assets.

The "glitch" look (see the Cayman GT4 Cloudflare concept) is a dispersion field:
angular convex shards — sharp triangles and thin quads — in a small palette, whose
density and size ramp along a flow axis so the wrap reads as a solid mass shattering
and flying off toward one end.

This produces *reusable* assets for hand compositing in GIMP / Affinity, not one
baked livery: transparent RGBA PNGs with anti-aliased edges, exported both as a
combined sheet and as one layer per palette colour (so you can drop each layer,
set a blend mode, recolour, and mask it per panel).

Nothing here touches a car template — it's pure pattern generation. Feed the output
into the compositor by hand now; later the renderer can place a shard field as a
fill/element keyed to a zone.

Design knobs (all on GlitchParams):
  direction_deg  flow axis the shards disperse along (0 = +x / toward the right)
  density        shards toward the dense (source) end vs the sparse (leading) end
  size           shard size at the source; shards shrink toward the leading edge
  jitter         how irregular each shard is (0 = regular, 1 = jagged)
  elongation     how raked/streaky shards are along the flow axis
  palette        hex colours; palette_weights biases the mix (orange-dominant, etc.)

Usage:
    python -m iracing_painter.glitch --out out/glitch \\
        --size 4096x2048 --direction 200 --seed 7
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# Cloudflare-concept palette: orange dominant, charcoal, white accents.
CLOUDFLARE = ["#f38020", "#2b2b2b", "#f4f4f4"]
DEFAULT_WEIGHTS = [0.62, 0.30, 0.08]


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@dataclass
class GlitchParams:
    width: int = 4096
    height: int = 2048
    direction_deg: float = 0.0          # flow axis (shards disperse toward this)
    palette: list[str] = field(default_factory=lambda: list(CLOUDFLARE))
    palette_weights: list[float] = field(default_factory=lambda: list(DEFAULT_WEIGHTS))
    seed: int = 0
    # Density ramp along the flow axis: prob of a shard at the source vs leading end.
    density_source: float = 1.0
    density_edge: float = 0.0
    density_gamma: float = 3.2          # >1 = dissolve concentrated near the edge
    # Two shard scales (big plates + small flecks) layered for a natural shatter.
    cells_major: int = 42               # ~big shards across the long axis
    cells_minor: int = 120              # ~flecks across the long axis
    fleck_fraction: float = 0.40        # share of points that are flecks
    size_source: float = 1.35           # shard size multiplier at the source
    size_edge: float = 0.28             # ...shrinking toward the leading edge
    jitter: float = 0.60                # vertex irregularity 0..1
    elongation: float = 1.6             # stretch along flow axis (1 = none)
    rotation_jitter_deg: float = 26.0   # spread of shard rake around the flow axis
    margin: float = 0.06                # keep shards off the very edge (avoid clipping)
    supersample: int = 3                # render scale for anti-aliased alpha
    background: bool = False            # solid bg instead of transparent (debug)


def _ramp(t: np.ndarray, a: float, b: float, gamma: float) -> np.ndarray:
    """a at t=0 (source) -> b at t=1 (leading edge), with a gamma curve."""
    return a + (b - a) * np.power(np.clip(t, 0.0, 1.0), gamma)


def _shard_polygon(rng, cx, cy, r, ux, uy, p: GlitchParams):
    """An irregular convex shard centred at (cx,cy), raked along (ux,uy)."""
    n = int(rng.integers(3, 6))              # triangles..pentagons -> angular
    base = np.sort(rng.uniform(0, 2 * np.pi, n))
    # Push vertex angles apart a touch so we don't get slivers every time.
    radii = r * (1.0 - p.jitter * rng.uniform(0.0, 1.0, n))
    pts = []
    rake = np.deg2rad(rng.uniform(-p.rotation_jitter_deg, p.rotation_jitter_deg))
    ca, sa = np.cos(rake), np.sin(rake)
    for ang, rad in zip(base, radii):
        # Local point, elongated along local x (flow), then rotate into flow frame.
        lx = np.cos(ang) * rad * p.elongation
        ly = np.sin(ang) * rad
        rx = lx * ca - ly * sa
        ry = lx * sa + ly * ca
        # Map local (flow, perp) -> image using the flow unit vector (ux,uy).
        px = cx + rx * ux - ry * uy
        py = cy + rx * uy + ry * ux
        pts.append((float(px), float(py)))
    return pts


def _scatter(p: GlitchParams):
    """Yield (polygon, color_index) shards across the canvas."""
    rng = np.random.default_rng(p.seed)
    W, H = p.width, p.height
    theta = np.deg2rad(p.direction_deg)
    ux, uy = np.cos(theta), np.sin(theta)    # flow unit vector
    # Project a point onto the flow axis -> normalized 0 (source) .. 1 (edge).
    # Source is the trailing end opposite the flow direction.
    corners = np.array([[0, 0], [W, 0], [0, H], [W, H]], float)
    proj_c = corners[:, 0] * ux + corners[:, 1] * uy
    lo, hi = proj_c.min(), proj_c.max()
    span = max(hi - lo, 1e-6)

    weights = np.array(p.palette_weights, float)
    weights = weights / weights.sum()
    long_axis = max(W, H)
    mx, my = p.margin * W, p.margin * H

    out = []
    for cells, is_fleck in ((p.cells_major, False), (p.cells_minor, True)):
        step = long_axis / cells
        nx = int(W / step) + 2
        ny = int(H / step) + 2
        base_r = step * (0.85 if not is_fleck else 0.5)
        for gx in range(nx):
            for gy in range(ny):
                # Jittered grid sample.
                cx = (gx + rng.uniform(0.2, 0.8)) * step
                cy = (gy + rng.uniform(0.2, 0.8)) * step
                if not (mx <= cx <= W - mx and my <= cy <= H - my):
                    continue
                t = ((cx * ux + cy * uy) - lo) / span
                dens = _ramp(np.array(t), p.density_source, p.density_edge, p.density_gamma)
                # Flecks bias toward the leading edge (they're the spray).
                if is_fleck:
                    if rng.uniform() > p.fleck_fraction:
                        continue
                    dens = dens * (0.4 + 0.9 * t)
                if rng.uniform() > float(dens):
                    continue
                size_mul = _ramp(np.array(t), p.size_source, p.size_edge, 1.4)
                r = base_r * float(size_mul) * rng.uniform(0.6, 1.15)
                poly = _shard_polygon(rng, cx, cy, r, ux, uy, p)
                ci = int(rng.choice(len(p.palette), p=weights))
                out.append((poly, ci))
    return out


def _render_layer(shards, p: GlitchParams, only_index: int | None = None) -> Image.Image:
    s = p.supersample
    W, H = p.width * s, p.height * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rgb = [_hex_to_rgb(c) for c in p.palette]
    for poly, ci in shards:
        if only_index is not None and ci != only_index:
            continue
        pts = [(x * s, y * s) for (x, y) in poly]
        draw.polygon(pts, fill=(*rgb[ci], 255))
    if s != 1:
        img = img.resize((p.width, p.height), Image.LANCZOS)
    if p.background:
        bg = Image.new("RGBA", img.size, (18, 18, 22, 255))
        bg.alpha_composite(img)
        img = bg
    return img


def generate(p: GlitchParams, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shards = _scatter(p)

    files = {}
    combined = _render_layer(shards, p)
    combined.save(out_dir / "glitch_combined.png")
    files["combined"] = "glitch_combined.png"

    # One transparent layer per palette colour for blend-mode compositing.
    for i, hexc in enumerate(p.palette):
        layer = _render_layer(shards, p, only_index=i)
        name = f"glitch_layer{i}_{hexc.lstrip('#')}.png"
        layer.save(out_dir / name)
        files[f"layer{i}"] = name

    meta = {"params": asdict(p), "shard_count": len(shards), "files": files}
    (out_dir / "glitch_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def _parse_size(s: str) -> tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate transparent glitch shard assets.")
    ap.add_argument("--out", default="out/glitch", help="output directory")
    ap.add_argument("--size", type=_parse_size, default=(4096, 2048), help="WxH, e.g. 4096x2048")
    ap.add_argument("--direction", type=float, default=0.0, help="flow direction in degrees")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--palette", nargs="*", default=None, help="hex colours, e.g. #f38020 #2b2b2b")
    ap.add_argument("--weights", nargs="*", type=float, default=None)
    ap.add_argument("--debug-bg", action="store_true", help="render on a dark background")
    args = ap.parse_args()

    p = GlitchParams(width=args.size[0], height=args.size[1],
                     direction_deg=args.direction, seed=args.seed,
                     background=args.debug_bg)
    if args.palette:
        p.palette = args.palette
    if args.weights:
        p.palette_weights = args.weights

    meta = generate(p, args.out)
    print(f"{meta['shard_count']} shards -> {args.out}")
    for k, v in meta["files"].items():
        print(f"  {k}: {v}")
