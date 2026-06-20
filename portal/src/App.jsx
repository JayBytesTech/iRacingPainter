import { useEffect, useMemo, useRef, useState } from 'react'

const TEMPLATE = 'porsche_992_gt3'

export default function App() {
  const [meta, setMeta] = useState(null)
  const [name, setName] = useState('My Livery')
  const [baseColor, setBaseColor] = useState('#1a1a1a')
  // overrides: { [zoneOrGroup]: { enabled: bool, color: '#rrggbb' } }
  const [overrides, setOverrides] = useState({})
  const [preview, setPreview] = useState(null)
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
  }, [])

  const spec = useMemo(() => {
    const zones = {}
    for (const [k, v] of Object.entries(overrides)) {
      if (v.enabled) zones[k] = { fill: { type: 'solid', color: v.color } }
    }
    const s = {
      schema_version: '0.1',
      template: TEMPLATE,
      meta: { name },
      base: { fill: { type: 'solid', color: baseColor } },
    }
    if (Object.keys(zones).length) s.zones = zones
    return s
  }, [name, baseColor, overrides])

  // Debounced live preview.
  useEffect(() => {
    if (!meta) return
    clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await fetch('/api/render', {
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
  }, [spec, meta])

  function toggle(key) {
    setOverrides((o) => ({ ...o, [key]: { ...o[key], enabled: !o[key].enabled } }))
  }
  function setColor(key, color) {
    setOverrides((o) => ({ ...o, [key]: { ...o[key], color, enabled: true } }))
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
          <div className="field swatch-base">
            <label>Body (base) color</label>
            <input type="color" value={baseColor} onChange={(e) => setBaseColor(e.target.value)} />
          </div>
        </div>

        <div className="section">
          <h2>Zone groups</h2>
          {Object.keys(meta.groups).map((g) => (
            <Row key={g} k={g} label={g} group ov={overrides[g]} toggle={toggle} setColor={setColor} />
          ))}
        </div>

        <div className="section">
          <h2>Panels</h2>
          {meta.zones.map((z) => (
            <Row key={z} k={z} label={z} ov={overrides[z]} toggle={toggle} setColor={setColor} />
          ))}
        </div>

        <div className="section">
          <button className="btn" onClick={exportTgas}>Export TGAs (.zip)</button>
        </div>
      </div>

      <div className="main">
        {loading && <div className="loading">rendering…</div>}
        {preview && (
          <div className="preview-wrap">
            <img src={preview} alt="livery preview" />
          </div>
        )}
        <p className="note">Flat UV preview (the car's unwrapped skin). 3D preview is a later milestone.</p>
        {warnings.map((w, i) => <p className="warn" key={i}>⚠ {w}</p>)}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}

function Row({ k, label, ov, toggle, setColor, group }) {
  if (!ov) return null
  return (
    <div className={`row ${ov.enabled ? '' : 'off'}`}>
      <input type="checkbox" checked={ov.enabled} onChange={() => toggle(k)} />
      <span className={`name ${group ? 'group-name' : ''}`}>{label}</span>
      <input
        type="color"
        value={ov.color}
        disabled={!ov.enabled}
        onChange={(e) => setColor(k, e.target.value)}
      />
    </div>
  )
}
