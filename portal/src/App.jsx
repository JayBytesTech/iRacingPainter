import { useEffect, useMemo, useRef, useState } from 'react'

const TEMPLATE = 'porsche_992_gt3'

export default function App() {
  const [meta, setMeta] = useState(null)
  const [name, setName] = useState('My Livery')
  const [baseColor, setBaseColor] = useState('#1a1a1a')
  // Stock pattern: null = plain solid base. Otherwise an id from the manifest.
  const [patterns, setPatterns] = useState([])
  const [pattern, setPattern] = useState(null)
  const [patColors, setPatColors] = useState(['#0a1f44', '#f2f2f2', '#b11226'])
  // overrides: { [zoneOrGroup]: { enabled: bool, color: '#rrggbb' } }
  const [overrides, setOverrides] = useState({})
  // Finish: whole-car default + per-zone overrides ('default' = inherit).
  const [defaultMaterial, setDefaultMaterial] = useState('gloss')
  const [zoneMaterials, setZoneMaterials] = useState({})
  // Racing number element.
  const [number, setNumber] = useState({
    enabled: false, value: '24', color: '#ffffff', outlineEnabled: false, outline: '#101010',
  })
  // Logos: available assets + the placed instances on this livery.
  const [assets, setAssets] = useState([])
  const [logos, setLogos] = useState([]) // [{ id, asset, zone, scale, rotation, opacity }]
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef(null)
  const logoId = useRef(1)
  const [preview, setPreview] = useState(null)
  const [view, setView] = useState('color') // 'color' | 'spec'
  const [error, setError] = useState(null)
  const [warnings, setWarnings] = useState([])
  const [loading, setLoading] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    fetch(`/api/templates/${TEMPLATE}`)
      .then((r) => r.json())
      .then((m) => {
        setMeta(m)
        const init = {}
        for (const z of m.zones) init[z] = { enabled: false, color: '#ffffff' }
        for (const g of Object.keys(m.groups)) init[g] = { enabled: false, color: '#ffffff' }
        setOverrides(init)
      })
      .catch((e) => setError(String(e)))
    fetch(`/api/templates/${TEMPLATE}/patterns`)
      .then((r) => r.json())
      .then((p) => setPatterns(p))
      .catch(() => {})
    loadAssets()
  }, [])

  function loadAssets() {
    fetch('/api/assets')
      .then((r) => r.json())
      .then((a) => setAssets(a))
      .catch(() => {})
  }

  // Anchor targets for a logo: groups + zones.
  const anchorTargets = useMemo(
    () => (meta ? [...Object.keys(meta.groups), ...meta.zones] : []),
    [meta],
  )

  const activePattern = patterns.find((p) => p.id === pattern) || null

  const spec = useMemo(() => {
    const zones = {}
    for (const [k, v] of Object.entries(overrides)) {
      if (v.enabled) zones[k] = { fill: { type: 'solid', color: v.color } }
    }
    let baseFill
    if (activePattern) {
      baseFill = activePattern.recolor
        ? { type: 'pattern', pattern: activePattern.id, colors: patColors }
        : { type: 'pattern', pattern: activePattern.id, colors: ['#000000'] }
    } else {
      baseFill = { type: 'solid', color: baseColor }
    }
    const s = {
      schema_version: '0.1',
      template: TEMPLATE,
      meta: { name },
      base: { fill: baseFill },
    }
    if (Object.keys(zones).length) s.zones = zones

    // Materials: emit default only when it differs from the engine baseline.
    const materials = {}
    if (defaultMaterial !== 'gloss') materials.default = defaultMaterial
    const zmats = {}
    for (const [k, v] of Object.entries(zoneMaterials)) {
      if (v && v !== 'default') zmats[k] = v
    }
    if (Object.keys(zmats).length) materials.zones = zmats
    if (Object.keys(materials).length) s.materials = materials

    // Elements: logos (in order), then the racing number on top.
    const elements = []
    for (const lg of logos) {
      if (!lg.asset || !lg.zone) continue
      const el = { type: 'logo', asset: lg.asset, zone: lg.zone, scale: lg.scale }
      if (lg.rotation) el.rotation = lg.rotation
      if (lg.opacity < 1) el.opacity = lg.opacity
      elements.push(el)
    }
    if (number.enabled && number.value.trim()) {
      const el = { type: 'number', value: number.value.trim(), color: number.color }
      if (number.outlineEnabled) el.outline = number.outline
      elements.push(el)
    }
    if (elements.length) s.elements = elements

    return s
  }, [name, baseColor, overrides, activePattern, patColors, defaultMaterial, zoneMaterials, number, logos])

  // Debounced live preview.
  useEffect(() => {
    if (!meta) return
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await fetch(`/api/render?view=${view}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(spec),
        })
        if (!res.ok) {
          const detail = await res.json().catch(() => ({}))
          setError(detail.detail || `render failed (${res.status})`)
          setLoading(false)
          return
        }
        const blob = await res.blob()
        setPreview((old) => {
          if (old) URL.revokeObjectURL(old)
          return URL.createObjectURL(blob)
        })
        setError(null)
        // fetch warnings in parallel (non-blocking)
        fetch('/api/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(spec),
        })
          .then((r) => r.json())
          .then((v) => setWarnings(v.warnings || []))
          .catch(() => {})
      } catch (e) {
        setError(String(e))
      }
      setLoading(false)
    }, 250)
    return () => clearTimeout(timer.current)
  }, [spec, meta, view])

  function toggle(key) {
    setOverrides((o) => ({ ...o, [key]: { ...o[key], enabled: !o[key].enabled } }))
  }
  function setColor(key, color) {
    setOverrides((o) => ({ ...o, [key]: { ...o[key], color, enabled: true } }))
  }
  function setMaterial(key, mat) {
    setZoneMaterials((m) => ({ ...m, [key]: mat }))
  }

  async function uploadLogo(fileList) {
    const file = fileList?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/assets', { method: 'POST', body: fd })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(d.detail || 'upload failed')
      } else {
        loadAssets()
        addLogo(d.name)
      }
    } catch (e) {
      setError(String(e))
    }
    setUploading(false)
    if (fileInput.current) fileInput.current.value = ''
  }

  function addLogo(asset) {
    setLogos((ls) => [
      ...ls,
      { id: logoId.current++, asset, zone: anchorTargets[0] || 'hood', scale: 0.5, rotation: 0, opacity: 1 },
    ])
  }
  function updateLogo(id, patch) {
    setLogos((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)))
  }
  function removeLogo(id) {
    setLogos((ls) => ls.filter((l) => l.id !== id))
  }

  async function exportTgas() {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(spec),
    })
    if (!res.ok) {
      const d = await res.json().catch(() => ({}))
      setError(d.detail || 'export failed')
      return
    }
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${name.replace(/\s+/g, '_') || 'livery'}_tga.zip`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (!meta) return <div className="app"><div className="main">Loading template…</div></div>

  return (
    <div className="app">
      <div className="sidebar">
        <div className="header">
          <h1>iRacing <span className="tag">Painter</span></h1>
        </div>
        <p className="subtitle">{meta.name}</p>

        <div className="section">
          <div className="field">
            <label>Livery name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          {!activePattern && (
            <div className="field swatch-base">
              <label>Body (base) color</label>
              <input type="color" value={baseColor} onChange={(e) => setBaseColor(e.target.value)} />
            </div>
          )}
          <div className="field">
            <label>Finish (whole car)</label>
            <select value={defaultMaterial} onChange={(e) => setDefaultMaterial(e.target.value)}>
              {meta.materials.map((mt) => (
                <option key={mt} value={mt}>{mt}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="section">
          <h2>Design</h2>
          <div className="pattern-grid">
            <button
              className={`pattern-tile ${activePattern ? '' : 'sel'}`}
              onClick={() => setPattern(null)}
              title="Solid color"
            >
              <span className="pattern-none">Solid</span>
            </button>
            {patterns.map((p) => (
              <button
                key={p.id}
                className={`pattern-tile ${pattern === p.id ? 'sel' : ''}`}
                onClick={() => setPattern(p.id)}
                title={p.name + (p.recolor ? '' : ' (fixed colors)')}
              >
                <img
                  src={`/api/templates/${TEMPLATE}/patterns/${p.id}/thumb`}
                  alt={p.name}
                  loading="lazy"
                />
              </button>
            ))}
          </div>

          {activePattern && activePattern.recolor && (
            <div className="pattern-colors">
              {patColors.map((c, i) => (
                <div className="field swatch-base" key={i}>
                  <label>Color {i + 1}</label>
                  <input
                    type="color"
                    value={c}
                    onChange={(e) =>
                      setPatColors((cs) => cs.map((x, j) => (j === i ? e.target.value : x)))
                    }
                  />
                </div>
              ))}
            </div>
          )}
          {activePattern && !activePattern.recolor && (
            <p className="note">{activePattern.name} has fixed colors (baked design).</p>
          )}
        </div>

        <div className="section">
          <h2>Number</h2>
          <div className="row">
            <input
              type="checkbox"
              checked={number.enabled}
              onChange={() => setNumber((n) => ({ ...n, enabled: !n.enabled }))}
            />
            <span className="name">Show number</span>
          </div>
          {number.enabled && (
            <>
              <div className="field">
                <label>Number (1–3 chars)</label>
                <input
                  type="text"
                  maxLength={3}
                  value={number.value}
                  onChange={(e) => setNumber((n) => ({ ...n, value: e.target.value }))}
                />
              </div>
              <div className="row">
                <span className="name">Color</span>
                <input
                  type="color"
                  value={number.color}
                  onChange={(e) => setNumber((n) => ({ ...n, color: e.target.value }))}
                />
              </div>
              <div className={`row ${number.outlineEnabled ? '' : 'off'}`}>
                <input
                  type="checkbox"
                  checked={number.outlineEnabled}
                  onChange={() => setNumber((n) => ({ ...n, outlineEnabled: !n.outlineEnabled }))}
                />
                <span className="name">Outline</span>
                <input
                  type="color"
                  value={number.outline}
                  disabled={!number.outlineEnabled}
                  onChange={(e) => setNumber((n) => ({ ...n, outline: e.target.value }))}
                />
              </div>
            </>
          )}
        </div>

        <div className="section">
          <h2>Logos</h2>
          <div className="asset-gallery">
            {assets.map((a) => (
              <button
                key={a.name}
                className="asset-tile"
                title={`${a.name} — add to livery`}
                onClick={() => addLogo(a.name)}
              >
                <img src={`/api/assets/${a.name}/image`} alt={a.name} loading="lazy" />
                <span>{a.name}</span>
              </button>
            ))}
          </div>
          <input
            ref={fileInput}
            type="file"
            accept=".png,.svg,image/png,image/svg+xml"
            style={{ display: 'none' }}
            onChange={(e) => uploadLogo(e.target.files)}
          />
          <button className="btn btn-sec" disabled={uploading} onClick={() => fileInput.current?.click()}>
            {uploading ? 'Uploading…' : 'Upload logo (PNG/SVG)'}
          </button>

          {logos.map((lg) => (
            <div className="logo-card" key={lg.id}>
              <div className="logo-card-head">
                <img src={`/api/assets/${lg.asset}/image`} alt={lg.asset} />
                <span className="name">{lg.asset}</span>
                <button className="x" onClick={() => removeLogo(lg.id)} title="Remove">✕</button>
              </div>
              <div className="field">
                <label>Anchor zone</label>
                <select value={lg.zone} onChange={(e) => updateLogo(lg.id, { zone: e.target.value })}>
                  {anchorTargets.map((z) => <option key={z} value={z}>{z}</option>)}
                </select>
              </div>
              <label className="slider">
                Size {Math.round(lg.scale * 100)}%
                <input type="range" min="0.1" max="1.5" step="0.05" value={lg.scale}
                  onChange={(e) => updateLogo(lg.id, { scale: parseFloat(e.target.value) })} />
              </label>
              <label className="slider">
                Rotation {lg.rotation}°
                <input type="range" min="-180" max="180" step="5" value={lg.rotation}
                  onChange={(e) => updateLogo(lg.id, { rotation: parseInt(e.target.value) })} />
              </label>
              <label className="slider">
                Opacity {Math.round(lg.opacity * 100)}%
                <input type="range" min="0.1" max="1" step="0.05" value={lg.opacity}
                  onChange={(e) => updateLogo(lg.id, { opacity: parseFloat(e.target.value) })} />
              </label>
            </div>
          ))}
        </div>

        <div className="section">
          <h2>Zone groups</h2>
          {Object.keys(meta.groups).map((g) => (
            <Row key={g} k={g} label={g} group ov={overrides[g]} toggle={toggle} setColor={setColor}
              materials={meta.materials} mat={zoneMaterials[g]} setMaterial={setMaterial} />
          ))}
        </div>

        <div className="section">
          <h2>Panels</h2>
          {meta.zones.map((z) => (
            <Row key={z} k={z} label={z} ov={overrides[z]} toggle={toggle} setColor={setColor}
              materials={meta.materials} mat={zoneMaterials[z]} setMaterial={setMaterial} />
          ))}
        </div>

        <div className="section">
          <button className="btn" onClick={exportTgas}>Export TGAs (.zip)</button>
        </div>
      </div>

      <div className="main">
        {loading && <div className="loading">rendering…</div>}
        <div className="view-toggle">
          <button className={view === 'color' ? 'sel' : ''} onClick={() => setView('color')}>Color</button>
          <button className={view === 'spec' ? 'sel' : ''} onClick={() => setView('spec')}>Spec map</button>
        </div>
        {preview && (
          <div className="preview-wrap">
            <img src={preview} alt="livery preview" />
          </div>
        )}
        <p className="note">
          {view === 'spec'
            ? 'Spec map (material finish): R=metallic, G=roughness, B=clearcoat.'
            : 'Flat UV preview (the car’s unwrapped skin). 3D preview is a later milestone.'}
        </p>
        {warnings.map((w, i) => <p className="warn" key={i}>⚠ {w}</p>)}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}

function Row({ k, label, ov, toggle, setColor, group, materials, mat, setMaterial }) {
  if (!ov) return null
  return (
    <div className={`row ${ov.enabled ? '' : 'off'}`}>
      <input type="checkbox" checked={ov.enabled} onChange={() => toggle(k)} />
      <span className={`name ${group ? 'group-name' : ''}`}>{label}</span>
      {materials && (
        <select
          className="mat-select"
          value={mat || 'default'}
          title="Finish"
          onChange={(e) => setMaterial(k, e.target.value)}
        >
          <option value="default">finish…</option>
          {materials.map((mt) => (
            <option key={mt} value={mt}>{mt}</option>
          ))}
        </select>
      )}
      <input
        type="color"
        value={ov.color}
        disabled={!ov.enabled}
        onChange={(e) => setColor(k, e.target.value)}
      />
    </div>
  )
}
