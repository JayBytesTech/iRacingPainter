# Calibration livery — capture & decode protocol

Goal: from in-sim photos/video of a calibration livery, recover the ground truth we
can't get from the flat UV alone — **which segment is which panel**, **how each UV
island is oriented/mirrored on the car**, **which edges meet in 3D (seams)**, and a
**rough 3D position map**. This verifies/fills `zones/labels.json` and closes the
seam graph car-wide (unblocking custom cross-panel designs).

Generate with:

```bash
python -m iracing_painter.calibrate templates/porsche_992_gt3
```

Outputs land in `templates/porsche_992_gt3/calibration/` (gitignored):
`segid.tga`, `uv_grid.tga`, `spec_matte.tga`, previews, `legend.png`, and
`decode_key.json` (the exact colour↔meaning formulas + per-segment palette/centroid/
label — this is what makes the shots decodable later).

## The two passes

| Pass | What it looks like | What it decodes |
|---|---|---|
| **segid** | every panel a distinct colour with its **segment number** printed, an **underline** on the UV-down edge, and a **cyan square** at the UV-origin corner | which segment = which physical panel; label verification; **mirroring/rotation** of each island |
| **uv_grid** | a smooth `R=x, G=y` colour gradient + black grid lines (thin 64px, bold 256px) | each pixel's colour → its **UV coordinate**; sample both sides of a seam → the two UVs that meet (**seams**); the wrapped grid shows **3D shape/curvature** |

Both use the same `spec_matte.tga` (fully matte, kills glare so colours read true).

## Applying in-sim

On the iRacing PC, for **each** colour pass, copy into the car's paint folder
(`Documents/iRacing/paint/<car_folder>/`):

- `segid.tga` → `car_<yourCustID>.tga`   (then capture; see below)
- `uv_grid.tga` → `car_<yourCustID>.tga` (replace, capture again)
- `spec_matte.tga` → `car_spec_<yourCustID>.tga` (leave in place for **both** passes)

(Trading Paints folder sync works too.) Re-enter the session / reload the paint after
swapping. **Confirm the exact folder path + your custID while there** — we also need
them to script one-command deploy later.

## Capture protocol (do this for BOTH passes)

Settings: a **neutral/overcast** time-of-day (avoid strong coloured sunlight — it
tints the gradient), HUD hidden, highest resolution you can, car clean (no dirt).

Shots — aim for full coverage; the same framing for both passes helps a lot:

- Straight-on: **front, rear, left, right**
- **Top / overhead** (and as high-angle as the replay cam allows — roof & deck matter)
- Four **3/4 views**: front-left, front-right, rear-left, rear-right
- **Low** front-3/4 and rear-3/4 (catches rockers, splitter, diffuser)
- Anything that looks ambiguous — extra angles never hurt

**Video is ideal:** a slow 360° orbit at two heights (belt-line and high) per pass,
plus a slow pass over the roof/deck. Frames give dense coverage for the uv_grid
decode. Both stills + an orbit video = best.

Name/organize files per pass (e.g. `segid_front.png`, `uvgrid_rear34L.png`, or just
two folders `segid/` and `uvgrid/`). Bring them back to the Claude Code session.

## How the shots get decoded (later, in-session)

1. **segid → identity & orientation.** Read each visible number = segment id; match it
   to the physical panel in view → write verified names into `zones/labels.json`. The
   underline (UV-down) + cyan tick (UV-origin corner) show how that island is
   rotated/mirrored vs the car. Resolves the open `_needs_insim` items: left/right
   sides, the true right rocker, whether seg62 belongs to the hood, and `roof=8`.
2. **uv_grid → seams & 3D.** Decode pixel colour → UV (`x=R/255·(W-1)`, `y=G/255·(H-1)`;
   grid lines re-anchor absolute UV under any shading). At each physical seam, sample
   both sides to get the two UV coords that meet → add to `zones/seams.json`, closing
   the roof/doors/rear gaps so `layout.py` can build one car-wide design space. The
   wrapped grid + multi-angle frames give a rough position map / 3D sense.
3. Re-run `layout.py`; cross-panel stripes/curves then flow across the whole car.

Everything needed to decode is in `calibration/decode_key.json` (palette, formulas,
centroids, current labels, open questions).
