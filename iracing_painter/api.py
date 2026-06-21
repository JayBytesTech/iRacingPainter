"""Service API over the livery engine.

A thin HTTP layer the web portal (and later the MCP server) share. Endpoints:
  GET  /api/templates/{id}      template meta: zones, groups, materials, resolution
  GET  /api/assets              available logos (name + license/source)
  POST /api/validate            {valid, warnings, error} for a spec
  POST /api/render              PNG preview for a spec (downscaled)
  POST /api/export              zip of color + spec TGAs

Run from the project root:
    uvicorn iracing_painter.api:app --reload
"""
from __future__ import annotations

import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .assets import AssetError, LocalAssetProvider
from .patterns import load_manifest, patterns_dir
from .render import build_color_image
from .spec import SpecError, validate
from .spec_map import MATERIALS, build_spec_map

TEMPLATES_ROOT = Path("templates")
PREVIEW_MAX = 1200

app = FastAPI(title="iRacing Painter API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/templates/{template_id}")
def get_template(template_id: str):
    tdir = TEMPLATES_ROOT / template_id
    if not (tdir / "meta.json").exists():
        raise HTTPException(404, f"unknown template {template_id!r}")
    meta = json.loads((tdir / "meta.json").read_text())
    labels = {}
    lpath = tdir / "zones" / "labels.json"
    if lpath.exists():
        labels = json.loads(lpath.read_text())
    return {
        "id": template_id,
        "name": meta.get("name", template_id),
        "resolution": meta.get("resolution"),
        "body_fill_color": meta.get("body_fill_color"),
        "zones": sorted(labels.get("zones", {})),
        "groups": labels.get("groups", {}),
        "materials": sorted(MATERIALS),
    }


@lru_cache(maxsize=4)
def _segments(template_id: str):
    """Cached (segments array, {segment_id: zone}, {zone: group}) for a template."""
    tdir = TEMPLATES_ROOT / template_id
    seg = np.array(Image.open(tdir / "zones" / "segments.png"))
    labels = json.loads((tdir / "zones" / "labels.json").read_text())
    seg_to_zone: dict[int, str] = {}
    for zone, ids in labels.get("zones", {}).items():
        for i in ids:
            seg_to_zone[int(i)] = zone
    zone_to_group: dict[str, str] = {}
    for group, zones in labels.get("groups", {}).items():
        for z in zones:
            zone_to_group.setdefault(z, group)
    return seg, seg_to_zone, zone_to_group


@app.get("/api/templates/{template_id}/zone_at")
def zone_at(template_id: str, x: int, y: int):
    """Resolve a UV pixel (template-resolution coords) to its zone/group."""
    tdir = TEMPLATES_ROOT / template_id
    if not (tdir / "zones" / "segments.png").exists():
        raise HTTPException(404, "template has no segment map")
    seg, seg_to_zone, zone_to_group = _segments(template_id)
    h, w = seg.shape[:2]
    xi, yi = max(0, min(w - 1, x)), max(0, min(h - 1, y))
    sid = int(seg[yi, xi])
    zone = seg_to_zone.get(sid)
    return {"segment": sid, "zone": zone, "group": zone_to_group.get(zone) if zone else None}


@app.get("/api/templates/{template_id}/patterns")
def list_patterns(template_id: str):
    tdir = TEMPLATES_ROOT / template_id
    if not (tdir / "meta.json").exists():
        raise HTTPException(404, f"unknown template {template_id!r}")
    return load_manifest(tdir)


@app.get("/api/templates/{template_id}/patterns/{pattern_id}/thumb")
def pattern_thumb(template_id: str, pattern_id: str):
    thumb = patterns_dir(TEMPLATES_ROOT / template_id) / "thumbs" / f"pattern_{pattern_id}.png"
    if not thumb.exists():
        raise HTTPException(404, "no such pattern thumbnail")
    return Response(thumb.read_bytes(), media_type="image/png")


@app.get("/api/assets")
def list_assets():
    p = LocalAssetProvider()
    out = []
    for name in p.names():
        m = p.manifest.get(name, {})
        out.append({"name": name, "license": m.get("license"), "source": m.get("source")})
    return out


@app.post("/api/assets")
async def upload_asset(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "asset too large (max 5 MB)")
    try:
        name = LocalAssetProvider().add(file.filename or "logo.png", data)
    except AssetError as e:
        raise HTTPException(400, str(e))
    return {"name": name}


@app.get("/api/assets/{name}/image")
def asset_image(name: str):
    try:
        img = LocalAssetProvider().get(name).convert("RGBA")
    except AssetError:
        raise HTTPException(404, f"unknown asset {name!r}")
    img.thumbnail((256, 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


async def _spec_from(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON body")


@app.post("/api/validate")
async def validate_spec(request: Request):
    spec = await _spec_from(request)
    try:
        _, warnings = validate(spec, TEMPLATES_ROOT)
    except SpecError as e:
        return {"valid": False, "warnings": [], "error": str(e)}
    return {"valid": True, "warnings": warnings, "error": None}


@app.post("/api/render")
async def render(request: Request, view: str = "color"):
    spec = await _spec_from(request)
    try:
        template_dir, _ = validate(spec, TEMPLATES_ROOT)
    except SpecError as e:
        raise HTTPException(400, str(e))
    if view == "spec":
        img = build_spec_map(spec, template_dir).convert("RGB")
    else:
        img = build_color_image(spec, template_dir).convert("RGB")
    img.thumbnail((PREVIEW_MAX, PREVIEW_MAX))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


@app.post("/api/export")
async def export(request: Request):
    spec = await _spec_from(request)
    try:
        template_dir, _ = validate(spec, TEMPLATES_ROOT)
    except SpecError as e:
        raise HTTPException(400, str(e))
    name = (spec.get("meta", {}).get("name") or "livery").strip().replace(" ", "_")
    color = build_color_image(spec, template_dir)
    specmap = build_spec_map(spec, template_dir)

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname, img, mode in [
            (f"{name}.tga", color, "RGBA"),
            (f"{name}_spec.tga", specmap, "RGB"),
        ]:
            b = io.BytesIO()
            img.convert(mode).save(b, format="TGA")
            z.writestr(fname, b.getvalue())
    zbuf.seek(0)
    return StreamingResponse(
        zbuf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}_tga.zip"'},
    )


# Serve the built portal (npm run build) if present, so one command runs everything.
_DIST = Path("portal/dist")
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="portal")
