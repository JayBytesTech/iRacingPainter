"""Central font resolution.

Avoids hardcoded paths that silently fall back to a tiny bitmap font. Resolves a
real bold sans font once, with sane fallbacks across distros.
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

_CANDIDATES = [
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
]
_resolved: str | None = None


def font_path() -> str | None:
    global _resolved
    if _resolved is not None:
        return _resolved
    for c in _CANDIDATES:
        if Path(c).exists():
            _resolved = c
            return c
    return None


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """A bold sans font at `size`, falling back to Pillow's scalable default."""
    p = font_path()
    if p:
        return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)  # Pillow >= 10.1 honors size
