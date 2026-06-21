"""MCP server exposing the livery engine as tools.

Same engine as the portal and the HTTP API (the livery spec stays the contract);
this front-end lets an MCP client — Claude Desktop or Claude Code — drive the whole
pipeline with tools: discover what a template offers, author a spec, validate it,
render a preview image, and export iRacing-ready TGAs.

Run (stdio transport):
    python -m iracing_painter.mcp_server

Register with Claude Code (.mcp.json) or Claude Desktop (claude_desktop_config.json):
    {"mcpServers": {"iracing-painter": {
        "command": "/abs/path/.venv/bin/python",
        "args": ["-m", "iracing_painter.mcp_server"]}}}
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from .assets import LocalAssetProvider
from .patterns import load_manifest
from .render import build_color_image
from .spec import SpecError, validate
from .spec_map import MATERIALS, build_spec_map
from .tga import save_tga

# The engine uses paths relative to the project root; anchor there so the server
# works no matter where the MCP client launches it from.
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
TEMPLATES_ROOT = Path("templates")
OUT_DIR = Path("out")
PREVIEW_MAX = 1200

mcp = FastMCP("iRacing Painter")


def _safe_name(spec: dict, fallback: str = "livery") -> str:
    name = (spec.get("meta", {}) or {}).get("name") or fallback
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_") or fallback


@mcp.tool()
def list_templates() -> list[dict]:
    """List available car templates (those extracted from a PSD and ready to paint)."""
    out = []
    for d in sorted(TEMPLATES_ROOT.glob("*")):
        meta = d / "meta.json"
        if not meta.exists():
            continue
        m = json.loads(meta.read_text())
        out.append({
            "id": d.name,
            "name": m.get("name", d.name),
            "extracted": (d / "base.png").exists(),
        })
    return out


@mcp.tool()
def get_template(template_id: str = "porsche_992_gt3") -> dict:
    """Everything needed to author a livery for a template: paintable zones and
    groups, available finishes (materials), stock patterns, and logo assets."""
    tdir = TEMPLATES_ROOT / template_id
    if not (tdir / "meta.json").exists():
        raise ValueError(f"unknown template {template_id!r}; try list_templates()")
    meta = json.loads((tdir / "meta.json").read_text())
    labels = {}
    lpath = tdir / "zones" / "labels.json"
    if lpath.exists():
        labels = json.loads(lpath.read_text())
    provider = LocalAssetProvider()
    return {
        "id": template_id,
        "name": meta.get("name", template_id),
        "resolution": meta.get("resolution"),
        "zones": sorted(labels.get("zones", {})),
        "groups": labels.get("groups", {}),
        "materials": sorted(MATERIALS),
        "patterns": [
            {"id": p["id"], "name": p["name"], "recolor": p["recolor"]}
            for p in load_manifest(tdir)
        ],
        "assets": [
            {"name": n, **{k: provider.manifest.get(n, {}).get(k) for k in ("license", "source")}}
            for n in provider.names()
        ],
    }


@mcp.tool()
def get_authoring_guide() -> str:
    """The livery-spec authoring reference (schema, fill types, examples, tips)."""
    guide = ROOT / "docs" / "AUTHORING.md"
    return guide.read_text() if guide.exists() else "AUTHORING.md not found."


@mcp.tool()
def validate_spec(spec: dict) -> dict:
    """Validate a livery spec against the contract. Returns {valid, warnings, error}."""
    try:
        _, warnings = validate(spec, TEMPLATES_ROOT)
    except SpecError as e:
        return {"valid": False, "warnings": [], "error": str(e)}
    return {"valid": True, "warnings": warnings, "error": None}


@mcp.tool()
def render_preview(spec: dict, view: str = "color") -> Image:
    """Render a livery spec to a PNG preview. view='color' (the paint) or
    'spec' (the material/finish spec map). Validates first."""
    try:
        template_dir, _ = validate(spec, TEMPLATES_ROOT)
    except SpecError as e:
        raise ValueError(f"invalid spec: {e}")
    img = (build_spec_map(spec, template_dir) if view == "spec"
           else build_color_image(spec, template_dir)).convert("RGB")
    img.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Image(data=buf.getvalue(), format="png")


@mcp.tool()
def export_tgas(spec: dict, name: str | None = None) -> dict:
    """Render and write iRacing-ready TGAs (color + spec map) to the out/ folder.
    Returns the absolute file paths."""
    try:
        template_dir, warnings = validate(spec, TEMPLATES_ROOT)
    except SpecError as e:
        raise ValueError(f"invalid spec: {e}")
    stem = name or _safe_name(spec)
    OUT_DIR.mkdir(exist_ok=True)
    color_path = save_tga(build_color_image(spec, template_dir), OUT_DIR / f"{stem}.tga", bits=32)
    spec_path = save_tga(build_spec_map(spec, template_dir), OUT_DIR / f"{stem}_spec.tga", bits=24)
    return {
        "color_tga": str(color_path.resolve()),
        "spec_tga": str(spec_path.resolve()),
        "warnings": warnings,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
