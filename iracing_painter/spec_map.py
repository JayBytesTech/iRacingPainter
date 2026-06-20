"""Generate the iRacing spec map (material finish) from a livery's materials.

Channels (confirmed from the template): R=metallic, G=roughness, B=clearcoat.

We start from the template's baseline spec map (`spec_base.png`), which already
carries the correct parts materials (carbon/glass/trim) and the default body
finish. Then we override only the body pixels per the livery's `materials`:
`default` applies to the whole body, `zones` override specific zones/groups.

Material -> (metallic, roughness, clearcoat). Values follow this template's
convention (clearcoat unused; gloss == the baked body default). Exact look is
tuned in-sim later; the channel mapping is what matters.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

MATERIALS = {
    "gloss": (0, 51, 0),      # non-metal, low roughness — standard glossy paint
    "matte": (0, 220, 0),     # non-metal, high roughness — flat finish
    "metallic": (200, 51, 0), # metallic flake, glossy
    "chrome": (255, 0, 0),    # full metal, mirror-smooth
}

DEFAULT_MATERIAL = "gloss"


def build_spec_map(spec: dict, template_dir: str | Path):
    """Return the spec map as an RGB image for a validated livery spec."""
    from .render import _zone_resolver  # local import to avoid a cycle

    template_dir = Path(template_dir)
    meta = json.loads((template_dir / "meta.json").read_text())
    body_color = np.array(meta["body_fill_color"], np.int16)

    spec_base = template_dir / "spec_base.png"
    if spec_base.exists():
        arr = np.array(Image.open(spec_base).convert("RGB"))
    else:  # no baseline: start all-default
        h, w = tuple(meta["resolution"])[::-1]
        arr = np.zeros((h, w, 3), np.uint8)

    base_rgb = np.array(Image.open(template_dir / "base.png").convert("RGB")).astype(
        np.int16
    )
    is_body = np.all(np.abs(base_rgb - body_color) <= 18, axis=-1)

    materials = spec.get("materials") or {}
    default = materials.get("default", DEFAULT_MATERIAL)
    arr[is_body] = MATERIALS[default]

    zone_mats = materials.get("zones") or {}
    if zone_mats:
        seg = np.array(Image.open(template_dir / "zones" / "segments.png"))
        resolve = _zone_resolver(template_dir)
        for zone, mat in zone_mats.items():
            ids = resolve(zone)
            if not ids:
                continue
            mask = np.isin(seg, ids) & is_body
            arr[mask] = MATERIALS[mat]

    return Image.fromarray(arr, "RGB")
