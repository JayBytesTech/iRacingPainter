# iRacing Painter

Automated livery generation for iRacing. Long-term goal: describe a livery in
plain language and get a complete paint (design, sponsors/logos, spec map)
rendered to iRacing-ready TGA files.

## Architecture

Two cleanly separated layers (do not blur them):

1. **Livery spec (JSON)** — *design intent*. Eventually produced by an LLM from
   a natural-language description. A small, validated schema.
2. **Deterministic renderer** — turns the spec into pixels. Reproducible,
   seam-aware, debuggable. Correctness lives here.

The bridge between "this rectangle on the 2048 canvas is the hood / left door /
roof" and the spec is the **zone map** — a one-time annotation of each car's UV
template. Everything (color fills, stripe continuity, decal placement, spec-map
materials) keys off it.

## Roadmap (v1 = "describe → usable Porsche paint in-sim")

See the PRD for full scope/architecture. Status:

- [x] **P0 Plumbing** — PSD ingest, guide-layer extraction, valid TGA round-trip. (`extract.py`, `tga.py`)
- [x] **P1a Zone map** — UV auto-segmentation + per-zone painting. (`zones.py`, `calibrate.py`)
- [~] **P1b Verify zones** — a two-pass **calibration livery** (`calibrate.py`:
      segment-ID + UV-gradient/grid) decodes identity, orientation, seams, and a
      rough 3D map from in-sim shots → finalizes `labels.json` and closes the seam
      graph car-wide. See `docs/CALIBRATION.md`. *(awaiting in-sim capture)*
- [x] **P2 Spec schema v0.1 + validator** — the contract; renderer consumes validated specs. (`schemas/`, `spec.py`)
- [~] **P3 Renderer features** — seam-safe done: zone groups (two-tone along
      boundaries) + number plates into template number blocks. Cross-panel stripes/
      curves deferred to the projection milestone (see PRD §12).
- [x] **P4 Asset library + logos** — local provider w/ licensing manifest; `logo`
      elements anchored to a zone/group centroid or explicit UV coords, with
      scale/rotation/opacity. (`assets.py`)
- [x] **P5 Spec-map generator** — baseline spec extracted from the template
      (keeps parts materials) + per-zone material overrides → 24-bit spec TGA.
      (`spec_map.py`; rendering now emits `<name>.tga` + `<name>_spec.tga`)
- [~] **P6 NL → spec** — done via Claude Code in-session (uses Jay's subscription,
      no API): describe a livery → Claude authors a validated spec → render. See
      `docs/AUTHORING.md`. Programmatic API deferred to the standalone/shared phase.
- [ ] **P7 Deploy/sync** — one command to push to the iRacing PC / Trading Paints.
- [x] **P8 Web portal + API** — FastAPI service (`api.py`) + React/Vite portal
      (`portal/`): the engine behind a live, app-like builder.
- [x] **P9 Stock patterns** — the template's built-in iRacing designs as
      recolorable presets (R/G/B channel masks → 3 colors). (`patterns.py`)
- [x] **P10–P12 Full portal builder** — finish (materials, racing number) +
      logo upload/placement + spec-map preview toggle + click-a-panel-to-select
      and click-to-place logos. The portal now drives most of the spec by mouse.
- [x] **P13 Seam discovery** — recover inter-panel seams from the stock patterns
      (structured-light fingerprint matching + RANSAC), no 3D model or screenshots.
      (`seams.py`)
- [x] **P14 Label audit** — number-blocks + decals + seam graph → corrected
      `zones/labels.json` (draft-v1); remaining sides flagged for in-sim check.
- [~] **P15 Cross-panel designs** — global design-space `layout.py` + a `stripes`
      fill that lines up across seams. Works *within* connected panel groups
      (front/sides); car-wide alignment is parked on the calibration screenshots.
- [x] **MCP server** — drive the whole engine as Claude tools (Desktop or Code):
      discover, validate, render preview, export. (`mcp_server.py`, `.mcp.json`)

## Template facts (Porsche 992 R GT3)

- 2048x2048 RGBA. Body fill color is a flat `#3e89cd` (62,137,205).
- Color TGA = the `Paintable Area` group. The `Turn Off Before Exporting TGA`
  group is guides only (UV `Wire`, `Mask`, `Sponsor Blocks`, `Number Blocks`,
  mandatory series decals) — never exported.
- **Spec map channels: Red = metallic, Green = roughness, Blue = clearcoat.**

## Usage

```bash
source .venv/bin/activate

# One-time per template: pull base + reference layers out of the PSD
python -m iracing_painter.extract templates/porsche_992_gt3

# Validate a livery spec against the v0.1 contract
python -m iracing_painter.spec liveries/zones_demo.json

# Render a livery spec to out/<name>.tga (validates first)
python -m iracing_painter.render liveries/zones_demo.json
```

## Livery spec

Liveries are JSON specs validated against `iracing_painter/schemas/livery-0.1.schema.json`.
Minimal example:

```json
{
  "schema_version": "0.1",
  "template": "porsche_992_gt3",
  "base": { "fill": { "type": "solid", "color": "#8a1322" } },
  "zones": { "roof": { "fill": { "type": "solid", "color": "#101010" } } }
}
```

Every fill is an object so new fill types (gradient/texture/generated) are additive.
v0.1 renders: solid `base`, `zones` (a zone *or group* name from `labels.json`), and
`number` elements (drawn into the template's number blocks). `materials` and other
element types are accepted/rendered in later phases.

Zone groups (e.g. `doors`, `rear`) are defined in `zones/labels.json` and usable
anywhere a zone name is.

**Stock patterns.** The `base` fill can instead be a `pattern` — one of the car's
built-in iRacing designs (the numbered patterns from the paint shop), recolored
with up to 3 colors:

```json
{ "base": { "fill": { "type": "pattern", "pattern": "007",
                      "colors": ["#0a1f44", "#f2f2f2", "#b11226"] } } }
```

iRacing encodes each pattern as a pure R/G/B channel mask (Red→color 1, Green→
color 2, Blue→color 3); the renderer maps those to your colors and blends the
anti-aliased edges. Zones still override on top and baked decals are preserved.
Patterns are extracted from the template PSD into `templates/<t>/patterns/`
(iRacing's IP — gitignored, regenerate with `extract`).

**Logos** come from the asset library (`assets/logos/`, with a `manifest.json` tracking
source/license). A `logo` element references an asset by name and is placed either
anchored to a zone/group (`"zone": "hood", "scale": 0.55`) or at explicit UV coords
(`"at": [x, y], "width": 180`), with optional `rotation` and `opacity`:

```json
{ "type": "logo", "asset": "apex", "zone": "hood", "scale": 0.55 }
```

**Materials** control finish via the spec map (`materials.default` + `materials.zones`,
each one of `gloss`/`matte`/`metallic`/`chrome`). Rendering a spec emits both
`<name>.tga` (color) and `<name>_spec.tga` (24-bit spec map), starting from the
template's baseline so parts (carbon/glass/trim) keep their finish.

## Web portal

A local React/Vite portal over a FastAPI service (the same engine; the spec stays
the contract). Build a livery with: a stock-pattern picker (recolored with 3
colors), base + per-zone/group color pickers, per-zone finish (material) controls,
a racing number, logo upload + placement (anchor to a panel, or click the preview
to drop it at exact UV coords; size/rotation/opacity), click-a-panel-to-select for
coloring, a Color / Spec-map preview toggle, live preview, and TGA export.

```bash
# 1. backend (from project root, venv active)
uvicorn iracing_painter.api:app --reload          # serves API on :8000

# 2a. dev frontend (hot reload, proxies /api -> :8000)
cd portal && npm install && npm run dev            # opens :5173

# 2b. OR build once and let the API serve it at :8000
cd portal && npm run build                         # then just run uvicorn
```

API endpoints: `GET /api/templates/{id}`, `GET /api/templates/{id}/zone_at?x=&y=`
(UV pixel → panel), `GET /api/templates/{id}/patterns` (+
`/{pattern_id}/thumb`), `GET /api/assets`, `POST /api/assets` (upload PNG/SVG),
`GET /api/assets/{name}/image`, `POST /api/validate`,
`POST /api/render?view=color|spec` (PNG), `POST /api/export` (zip of TGAs).

## MCP server

The same engine is also exposed as an [MCP](https://modelcontextprotocol.io) server
so an MCP client (Claude Desktop or Claude Code) can drive the whole pipeline with
tools — the spec stays the contract. Tools:

- `list_templates` / `get_template` — discover what a template offers (zones,
  groups, materials, stock patterns, logo assets).
- `get_authoring_guide` — the spec authoring reference (`docs/AUTHORING.md`).
- `validate_spec` — check a spec against the contract.
- `render_preview` — render a spec to a PNG (`view='color'` or `'spec'`), returned
  inline as an image.
- `export_tgas` — write iRacing-ready color + spec TGAs to `out/`.

Run it (stdio transport):

```bash
python -m iracing_painter.mcp_server
```

**Claude Code** picks it up automatically from the project's `.mcp.json`.
**Claude Desktop** — add to `claude_desktop_config.json` (use absolute paths):

```json
{
  "mcpServers": {
    "iracing-painter": {
      "command": "/abs/path/to/iRacing Painter/.venv/bin/python",
      "args": ["-m", "iracing_painter.mcp_server"]
    }
  }
}
```

Then just describe a livery — the client calls `get_template`, authors a spec,
`render_preview`s it, and `export_tgas` when you're happy.

## Getting a paint in-sim

iRacing is Windows-only; this repo just produces the `.tga`. On the machine
running iRacing, copy the rendered file to:

```
Documents/iRacing/paint/<car_folder>/car_<yourCustID>.tga
```

`<yourCustID>` is your iRacing member ID. Easiest path is **Trading Paints**,
which watches a folder and syncs automatically. Restart / re-enter the session
to see the paint. (We'll script this copy/sync step once we confirm the paths
on your iRacing PC.)
```
