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

## A — panel alignment from patterns (BUILT — see `seams.py`)

> **Update:** this works. Validated and implemented as `iracing_painter/seams.py`,
> which discovers an inter-panel seam graph from the patterns alone — no 3D model,
> no screenshots. See "Validated method & results" below; the original reasoning is
> kept underneath for context.

### Validated method & results

The decisive reframe: **two UV pixels that map to the same 3D point carry the same
color in *every* stock pattern.** The 24 recolorable patterns therefore act as a
structured-light code painted on the car — each pixel gets an `N×3` *fingerprint*
(its colour across all patterns). Panel edges adjacent in 3D but split across the
UV share matching fingerprints along their seam.

Pipeline (`seams.py`):
1. Per panel, sample an inward ring of edge pixels (a few px in, to dodge the green
   seam-line anti-aliasing) and build their fingerprints.
2. Match informative (high-variance) fingerprints across a panel pair with a
   **Lowe ratio test** — this is what defeats the flat-region confound: a true seam
   point has *one* distinctly-closest partner; a flat-region pixel has many
   equidistant ones and is rejected.
3. Fit a robust **affine transform (RANSAC)** between matched UV points. A real seam
   yields many inliers with a sub-pixel-coherent transform.

Validation on the Porsche 992 GT3: the rear-quarter pair (two islands ~880 px apart
in UV) matched with **212 inliers at ~1 px residual, 100% affine inliers** — a clean
geometric correspondence recovered from patterns alone. A full run found **13 seams**
across the car (most < 2 px residual), including for panels that were never
hand-labeled. Notably a `rear_wing ↔ rocker_right` seam corroborates the suspected
mislabel of segment 63 — i.e. the seam graph can also help *fix the zone labels*.

Output: `zones/seams.json` (gitignored, regenerate with
`python -m iracing_painter.seams <template>`): per seam `{a, b, inliers,
residual_px, transform, samples, a_zone, b_zone}`. The `transform` maps a point on
panel A's frame to its partner on panel B, so a design defined once can be
*continued across the seam* (proof: `out/seam_stripe_proof.png`).

Remaining work to a full projection pipeline: chain per-seam transforms into a
global layout (or a per-texel position field) so a design flows across *many*
panels, and expose cross-panel fills in the spec/renderer. The hard
correspondence problem — the part the PRD gated on a 3D model — is solved.

### Original reasoning (kept for context)


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

Caveats (anticipated, mostly resolved): it seemed indirect/noisy, but using *all*
patterns at once as a fingerprint code — plus the Lowe ratio test — gave a clean,
screenshot-free signal. In-sim calibration is now a nice-to-have cross-check, not a
prerequisite.

Reference montages (regenerate locally; not committed):
`out/patterns_raw_montage.png` (the R/G/B masks) and
`out/patterns_recolored_montage.png` (navy/white/crimson sample).
