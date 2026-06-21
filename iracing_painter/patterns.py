"""Stock paint patterns: iRacing's built-in livery designs as recolor maps.

iRacing ships each car template with a `Car Patterns` group of numbered designs
(`car_pattern_000`..NNN). They are encoded the way the sim's paint shop works
internally: as pure RGB channel masks where

    Red  (240,0,0) -> Color 1
    Green(0,240,0) -> Color 2
    Blue (0,0,240) -> Color 3

and in-between values are anti-aliased edges between regions. Feeding a pattern
three colors reproduces that exact stock design. A few patterns are instead fully
baked artwork (fixed colors); those carry `recolor: false` in the manifest and are
composited as-is.

This module is the small shared core (recolor maths + IO) used by both the PSD
extractor (to pull patterns + build thumbnails) and the renderer.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# Neutral 3-tone scheme used for gallery thumbnails so a design reads clearly
# regardless of the colors a user will later choose.
THUMB_SCHEME = ((38, 38, 38), (232, 232, 232), (200, 16, 46))

# A pixel "belongs" to a channel slot if that channel dominates and the others
# are near zero; used to decide whether a pattern is a clean recolor map.
def _channel_purity(arr: np.ndarray) -> float:
    rgb = arr[..., :3].astype(np.int16)
    mx = rgb.max(axis=2)
    mid = np.sort(rgb, axis=2)[..., 1]
    pure = (mx > 100) & (mid < 70)
    return float(pure.mean())


def is_recolorable(arr: np.ndarray, threshold: float = 0.55) -> bool:
    """True if the pattern is a clean R/G/B channel map (vs. baked artwork)."""
    return _channel_purity(arr) >= threshold


def recolor(arr: np.ndarray, colors) -> np.ndarray:
    """Map a pattern's R/G/B channels to up to 3 colors, blending AA edges.

    `colors` is a sequence of (r,g,b); fewer than 3 are padded by repeating the
    last. Returns an (H,W,3) uint8 array.
    """
    cols = [np.array(c, float) for c in colors[:3]]
    while len(cols) < 3:
        cols.append(cols[-1] if cols else np.zeros(3))
    w = arr[..., :3].astype(float) / 240.0
    wsum = w.sum(axis=2, keepdims=True)
    wsum[wsum == 0] = 1.0
    wn = w / wsum
    out = wn[..., 0:1] * cols[0] + wn[..., 1:2] * cols[1] + wn[..., 2:3] * cols[2]
    return np.clip(out, 0, 255).astype(np.uint8)


def patterns_dir(template_dir: str | Path) -> Path:
    return Path(template_dir) / "patterns"


def load_manifest(template_dir: str | Path) -> list[dict]:
    """Return the pattern manifest (list of {id, name, recolor}) or []."""
    mpath = patterns_dir(template_dir) / "manifest.json"
    if not mpath.exists():
        return []
    return json.loads(mpath.read_text())


def manifest_entry(template_dir: str | Path, pattern_id: str) -> dict | None:
    for e in load_manifest(template_dir):
        if e["id"] == pattern_id:
            return e
    return None


def load_pattern(template_dir: str | Path, pattern_id: str) -> np.ndarray:
    """Load a pattern's RGB mask as an (H,W,3) array."""
    p = patterns_dir(template_dir) / f"pattern_{pattern_id}.png"
    return np.array(Image.open(p).convert("RGB"))
