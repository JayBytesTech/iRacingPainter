"""Asset library — resolve named logos/decals to images.

Curated local library now; the provider interface leaves room for AI-generated or
web-sourced providers later (per the PRD). A manifest tracks source/license, which
matters once liveries are shared.

Layout:
  assets/logos/manifest.json   {name: {file, source, license, note}}
  assets/logos/<file>.png      transparent PNG (or .svg if cairosvg is installed)
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


class AssetError(ValueError):
    """Raised when an asset can't be resolved."""


class LocalAssetProvider:
    """Resolves assets from a local directory + optional manifest."""

    def __init__(self, root: str | Path = "assets/logos"):
        self.root = Path(root)
        self.manifest: dict = {}
        mpath = self.root / "manifest.json"
        if mpath.exists():
            self.manifest = json.loads(mpath.read_text())

    def names(self) -> list[str]:
        names = set(self.manifest)
        if self.root.is_dir():
            names |= {p.stem for p in self.root.glob("*.png")}
            names |= {p.stem for p in self.root.glob("*.svg")}
        return sorted(names)

    def has(self, name: str) -> bool:
        return name in set(self.names())

    def get(self, name: str) -> Image.Image:
        """Return the asset as an RGBA image."""
        # Prefer a manifest entry; else look up <name>.png / <name>.svg.
        file = self.manifest.get(name, {}).get("file")
        candidates = [self.root / file] if file else []
        candidates += [self.root / f"{name}.png", self.root / f"{name}.svg"]
        for path in candidates:
            if path.exists():
                return _load_image(path)
        raise AssetError(
            f"unknown asset {name!r}; available: {self.names()}"
        )


def _load_image(path: Path) -> Image.Image:
    if path.suffix.lower() == ".svg":
        try:
            import cairosvg  # optional
        except ImportError:
            raise AssetError(
                f"{path.name} is SVG but cairosvg is not installed (pip install cairosvg)"
            ) from None
        import io

        png_bytes = cairosvg.svg2png(url=str(path))
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return Image.open(path).convert("RGBA")
