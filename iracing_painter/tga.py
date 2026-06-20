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


def save_tga(img: Image.Image, path: str | Path) -> Path:
    """Save an image as an iRacing-ready 32-bit uncompressed TGA."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    # compression default in Pillow's TGA writer is uncompressed.
    img.save(path, format="TGA")
    return path


def load_tga(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGBA")
