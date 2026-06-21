# Stock paint patterns & panel-alignment research

## The discovery

The template PSD's `Paintable Area` group contains a hidden `Car Patterns`
group: `car_pattern_000` … `car_pattern_024` (25 layers, full 2048×2048). These
are iRacing's built-in paint-shop designs — the numbered patterns you pick in the
sim and recolor with three colors.

Inspecting their pixels shows the encoding is **pure RGB channel masks**, exactly
how the sim's paint shop works internally:

| Channel value | Means        |
|---------------|--------------|
| Red `(240,0,0)`   | Color 1  |
| Green `(0,240,0)` | Color 2  |
| Blue `(0,0,240)`  | Color 3  |

In-between values (e.g. `(0,112,0)`) are anti-aliased edges between two regions.
So each pattern is a **3-slot recolor map**: feed three colors, blend by channel
weight, and you reproduce that stock design.

- **24 of 25** patterns are clean channel maps (`recolor: true`).
- **Pattern 1** is fully-baked artwork (black/red/white), not a channel map
  (`recolor: false`) — it composites as-is.
- Pattern 0 is near-solid (essentially "color 1 only").

`iracing_painter/patterns.py` implements the recolor maths and IO;
`extract.py::extract_patterns` pulls the layers into
`templates/<t>/patterns/` (gitignored — iRacing's IP) with a `manifest.json`
(`id`, `name`, `recolor`) and neutral-recolored gallery thumbnails.

## B — patterns as portal presets (DONE)

A `pattern` base-fill type was added to the spec contract (the architecture
always anticipated additive fill types). The portal gained a Design gallery:
pick a pattern, set 3 colors, live preview, export. Zones still override on top
and baked decals survive. This is effectively a local clone of iRacing's own
paint shop, with our extra zone/material controls on top.

## A — panel alignment from patterns (RESEARCH, not yet built)

Why these are useful beyond presets: each pattern is **already laid out correctly
in UV so it looks right in 3D**. A design feature that is *continuous in 3D* (e.g.
a center stripe running hood → roof → deck) appears in the pattern as **separate
UV fragments that share the same color region**, each positioned and rotated so
the pieces line up across the seam in 3D.

That makes the patterns a source of **cross-panel correspondence data**: for a
given color region, the set of UV islands it touches — and the relative
orientation of the fragment on each island — tells us which panel edges are
adjacent in 3D and how they're rotated/mirrored relative to each other. This is
exactly the information the **projection milestone** (PRD §12) needs to paint
across seams without a full 3D model.

Sketch of an extraction approach (future work):
1. For a recolorable pattern, threshold one channel (say green) to a binary mask.
2. Connected-component per UV island (intersect with the zone/segment map).
3. Group components that belong to the same 3D feature (same pattern + channel,
   geometrically continuous when projected).
4. From shared-feature fragments across islands, infer adjacency + relative
   transform between panel edges.

Caveats: it's indirect and noisy (one pattern only constrains the edges its
design happens to cross), so it's best **combined with the in-sim calibration
screenshots** (the parked PC track) rather than used alone. Banked as a research
input; not on the critical path.

Reference montages (regenerate locally; not committed):
`out/patterns_raw_montage.png` (the R/G/B masks) and
`out/patterns_recolored_montage.png` (navy/white/crimson sample).
