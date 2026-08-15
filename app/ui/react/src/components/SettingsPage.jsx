import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'

const SECTION_LABELS = {
  ai: 'AI / Classification',
  download: 'Download Client',
  web: 'Web UI',
  jellyfin: 'Jellyfin Integration',
  paths: 'Storage Paths',
  mcp: 'MCP Access Control',
}

const SECTION_ORDER = ['ai', 'download', 'web', 'jellyfin', 'paths', 'mcp']

export default function SettingsPage() {
  const { state, actions } = useAppStore()
  const entries = state.adminEnv?.spec || []
  const pending = state.adminEnvPending || []
  const [draft, setDraft] = useState({})
  const [revealed, setRevealed] = useState({})
  const [recreateVars, setRecreateVars] = useState([])
  const [saving, setSaving] = useState(false)
  const originalRef = useRef(null)

  useEffect(() => {
    if (entries.length && originalRef.current === null) {
      const originals = {}
      const initial = {}
      entries.forEach((e) => {
        originals[e.key] = e.secret ? '' : e.effective
        initial[e.key] = e.secret ? '' : e.effective
      })
      originalRef.current = originals
      setDraft(initial)
    }
  }, [entries])

  const sections = useMemo(() => {
    const grouped = {}
    entries.forEach((e) => {
      ;(grouped[e.section] = grouped[e.section] || []).push(e)
    })
    return SECTION_ORDER.filter((s) => grouped[s]).map((s) => ({ id: s, label: SECTION_LABELS[s] || s, items: grouped[s] }))
  }, [entries])

  function setField(key, value) {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  function toggleReveal(key) {
    setRevealed((r) => ({ ...r, [key]: !r[key] }))
  }

  function countChanges() {
    const originals = originalRef.current || {}
    let changed = 0
    entries.forEach((e) => {
      const value = draft[e.key]
      if (e.secret) {
        if (value && String(value).trim()) changed += 1
      } else if (String(value ?? '') !== String(originals[e.key] ?? '')) {
        changed += 1
      }
    })
    return changed
  }

  async function onSave() {
    if (saving) return
    const originals = originalRef.current || {}
    const updates = {}
    entries.forEach((e) => {
      const value = draft[e.key]
      if (e.secret) {
        const text = String(value ?? '').trim()
        if (text) updates[e.key] = text
      } else if (String(value ?? '') !== String(originals[e.key] ?? '')) {
        updates[e.key] = value ?? ''
      }
    })
    const keys = Object.keys(updates)
    if (!keys.length) {
      actions.toast('No changes to save', 'info')
      return
    }
    setSaving(true)
    try {
      const result = await actions.saveEnv(updates)
      actions.log('Settings saved: ' + keys.join(', '), 'good')
      actions.toast('Settings saved', 'good')
      if (result && result.needsRecreate && result.needsRecreate.length) {
        setRecreateVars(result.needsRecreate)
      } else {
        setRecreateVars([])
      }
      originalRef.current = null
      const next = {}
      entries.forEach((e) => {
        next[e.key] = e.secret ? '' : draft[e.key]
      })
      originalRef.current = next
    } catch (e) {
      /* error toast already shown by the store */
    } finally {
      setSaving(false)
    }
  }

  function renderInput(e) {
    if (e.type === 'bool') {
      return (
        <input
          type="checkbox"
          checked={!!draft[e.key]}
          onChange={(ev) => setField(e.key, ev.target.checked)}
          aria-label={e.key}
        />
      )
    }
    if (e.secret) {
      return (
        <div className="secret-field">
          <input
            type={revealed[e.key] ? 'text' : 'password'}
            value={draft[e.key] ?? ''}
            placeholder="Leave blank to keep unchanged"
            onChange={(ev) => setField(e.key, ev.target.value)}
            aria-label={e.key}
          />
          <button type="button" className="small" onClick={() => toggleReveal(e.key)} title={revealed[e.key] ? 'Hide' : 'Reveal'}>
            {revealed[e.key] ? 'Hide' : 'Reveal'}
          </button>
        </div>
      )
    }
    return (
      <input
        type={e.type === 'int' || e.type === 'float' ? 'number' : 'text'}
        step={e.type === 'float' ? 'any' : undefined}
        value={draft[e.key] ?? ''}
        onChange={(ev) => setField(e.key, ev.target.value)}
        aria-label={e.key}
      />
    )
  }

  return (
    <div className="admin-page">
      <div className="admin-header">
        <h2>Settings</h2>
        <div className="hint">Environment variables read from .env. Saving writes them to disk immediately.</div>
      </div>

      {recreateVars.length > 0 && (
        <div className="warn-box" role="alert">
          <strong>Recreate required</strong> — these changes need a container recreate to take effect:{' '}
          <code>{recreateVars.join(', ')}</code>
          <br />
          Run: <code>docker compose up -d --force-recreate</code>
        </div>
      )}

      {pending.length > 0 && (
        <div className="warn-box">
          <strong>Pending restart:</strong> {pending.join(', ')} differ from the running values.
        </div>
      )}

      {state.adminLoading && !entries.length ? (
        <div className="panel">
          <span className="spinner" /> Loading settings...
        </div>
      ) : (
        sections.map((section) => (
          <section className="panel" key={section.id}>
            <h2>{section.label}</h2>
            <div className="env-grid">
              {section.items.map((e) => {
                const isPending = pending.includes(e.key)
                return (
                  <div className="env-row" key={e.key}>
                    <div className="env-meta">
                      <div className="env-key">
                        {e.key}
                        {e.apply === 'restart' ? (
                          <span className="badge env-badge recreate" title="Applies after a container recreate">
                            recreate
                          </span>
                        ) : (
                          <span className="badge env-badge live" title="Applies immediately on save">
                            live
                          </span>
                        )}
                        {isPending && (
                          <span className="badge env-badge pending" title="Saved value differs from the running value">
                            pending
                          </span>
                        )}
                      </div>
                      <div className="env-desc">{e.description}</div>
                    </div>
                    <div className="env-input">{renderInput(e)}</div>
                  </div>
                )
              })}
            </div>
          </section>
        ))
      )}

      {entries.length > 0 && (
        <div className="admin-footer">
          <button type="button" className="primary" onClick={onSave} disabled={saving || !countChanges()}>
            {saving ? 'Saving...' : 'Save Changes'}
            {countChanges() > 0 ? ` (${countChanges()})` : ''}
          </button>
        </div>
      )}
    </div>
  )
}
