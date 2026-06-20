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

## Pipeline status

- [x] **Phase 0 — Plumbing.** Read the PSD, extract guide layers + clean base,
      write valid iRacing TGAs. (`extract.py`, `tga.py`)
- [~] **Phase 1 — Deterministic painter.** Body recolor works. Next: zone map,
      stripes / two-tone, number plates. (`render.py`)
- [ ] **Phase 2 — Asset library.** Sponsor logos, fonts, decals with anchors.
- [ ] **Phase 3 — Spec map.** R=metallic, G=roughness, B=clearcoat per zone.
- [ ] **Phase 4 — Describe-to-livery.** LLM → spec JSON (constrained).
- [ ] **Phase 5 — 3D preview.** Render texture onto the car model.

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

# Render a livery spec to out/<name>.tga
python -m iracing_painter.render liveries/example.json
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
