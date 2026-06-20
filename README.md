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
- [ ] **P1b Verify zones** — calibration screenshots → finalize `labels.json`. *(awaiting iRacing PC)*
- [x] **P2 Spec schema v0.1 + validator** — the contract; renderer consumes validated specs. (`schemas/`, `spec.py`)
- [~] **P3 Renderer features** — seam-safe done: zone groups (two-tone along
      boundaries) + number plates into template number blocks. Cross-panel stripes/
      curves deferred to the projection milestone (see PRD §12).
- [x] **P4 Asset library + logos** — local provider w/ licensing manifest; `logo`
      elements anchored to a zone/group centroid or explicit UV coords, with
      scale/rotation/opacity. (`assets.py`)
- [ ] **P5 Spec-map generator** — per-zone materials → spec TGA.
- [ ] **P6 NL → spec (Claude)** — description → validated spec, end-to-end.
- [ ] **P7 Deploy/sync** — one command to push to the iRacing PC / Trading Paints.

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

Zone groups (e.g. `rockers`, `rear`) are defined in `zones/labels.json` and usable
anywhere a zone name is.

**Logos** come from the asset library (`assets/logos/`, with a `manifest.json` tracking
source/license). A `logo` element references an asset by name and is placed either
anchored to a zone/group (`"zone": "hood", "scale": 0.55`) or at explicit UV coords
(`"at": [x, y], "width": 180`), with optional `rotation` and `opacity`:

```json
{ "type": "logo", "asset": "apex", "zone": "hood", "scale": 0.55 }
```

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
