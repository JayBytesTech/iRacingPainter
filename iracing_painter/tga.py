"""iRacing-compliant TGA read/write helpers.

iRacing custom paints are uncompressed 32-bit (RGBA) Targa files at the
template resolution. We standardize on:
  - mode RGBA
  - uncompressed (no RLE)
  - top-left origin (matches how Photoshop exports the templates)

Pillow handles the encoding; this module just enforces the conventions so
every file we hand to iRacing looks the same.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def save_tga(img: Image.Image, path: str | Path, bits: int = 32) -> Path:
    """Save an uncompressed TGA. bits=32 -> RGBA (color), bits=24 -> RGB (spec)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    target = "RGBA" if bits == 32 else "RGB"
    if img.mode != target:
        img = img.convert(target)
    # compression default in Pillow's TGA writer is uncompressed.
    img.save(path, format="TGA")
    return path


def load_tga(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGBA")
