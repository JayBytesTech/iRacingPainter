# Authoring liveries (NL → spec workflow)

This is the reference for turning a plain-language livery description into a valid
spec, **without the Claude API** — Claude Code (in-session, on Jay's subscription)
acts as the NL→spec engine. The deterministic pipeline does the rest.

> If you are a Claude Code session: read this before authoring a livery so you emit a
> valid spec on the first try. The spec is the contract; you only produce the JSON.

## Loop
1. User describes a livery in words.
2. Author `liveries/<name>.json` per the schema below.
3. Validate + render:
   ```bash
   python -m iracing_painter.render liveries/<name>.json
   ```
   This emits `out/<name>.tga` (color) + `out/<name>_spec.tga` (spec map).
4. Preview: convert the TGA to PNG and view it; iterate on user feedback.
5. When happy, the files are ready to deploy in-sim (P7 / manual copy for now).

## Spec schema (v0.1)
Validated against `iracing_painter/schemas/livery-0.1.schema.json`.

```json
{
  "schema_version": "0.1",
  "template": "porsche_992_gt3",
  "meta": { "name": "", "author": "", "description": "" },
  "palette": { "name": "#rrggbb" },
  "base": { "fill": { "type": "solid", "color": "#rrggbb" } },
  "zones": { "<zone-or-group>": { "fill": { "type": "solid", "color": "#rrggbb" } } },
  "elements": [
    { "type": "number", "value": "24", "color": "#rrggbb", "outline": "#rrggbb" },
    { "type": "logo", "asset": "apex", "zone": "hood", "scale": 0.55, "rotation": 0, "opacity": 1.0 },
    { "type": "logo", "asset": "volt", "at": [1024, 1024], "width": 200 }
  ],
  "materials": { "default": "gloss", "zones": { "<zone-or-group>": "matte" } }
}
```
- Required: `schema_version` (`"0.1"`), `template`, `base`.
- Every fill is an object (`{"type":"solid","color":...}`) — only `solid` for now.
- Colors are `#rrggbb`.

## Available for `porsche_992_gt3`
**Zones** (DRAFT — unverified until in-sim calibration; names/coverage may shift):
`roof`, `hood`, `front_bumper`, `rocker_left`, `rocker_right`, `rear_wing`,
`mirror_left`, `mirror_right`, `rear_quarter_left`, `rear_quarter_right`.

**Groups** (unions, usable anywhere a zone is): `rockers`, `mirrors`,
`rear_quarters`, `rear`.

**Logo assets**: `apex`, `volt` (placeholder originals; real sponsor library later).
List current assets from `assets/logos/manifest.json`.

**Materials**: `gloss`, `matte`, `metallic`, `chrome`.

## Conventions & current limits
- **Numbers** render into ALL of the template's number blocks (doors/hood/rear/etc.).
  Orientation flips are unverified until calibration.
- **Logos**: `zone` anchor = centered on that zone/group, sized as a fraction of its
  bbox via `scale`; OR explicit `at: [x,y]` + `width` (px). Exactly one of the two.
- **Seam-safe only.** Solid zone/group fills, within-panel logos, numbers. Do NOT
  attempt cross-panel stripes/curves/flags yet — they need the projection pipeline
  (PRD §12), not UV-space tricks. If a user asks for a wrap-around design, explain
  it's the next milestone and offer the seam-safe version.
- **Mandatory decals** (Porsche/iRacing/GT3R) are preserved automatically; don't
  recreate them.
- Mirrored/pre-decaled panels (e.g. some right-side panels) may not take body color —
  expected until calibration refines the labels.

## Tips for good results
- Pull a coherent `palette` first, then assign zones/groups from it.
- Default the body, override a few zones for contrast (roof/hood/rockers read well).
- Use `materials` for finish (e.g. matte roof, metallic body) — subtle but effective.
- Keep numbers high-contrast vs. their backing.
