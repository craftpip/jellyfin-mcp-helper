import { useEffect, useMemo, useRef, useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { apiGet } from '../api/apiClient.js'

const SECTION_LABELS = {
  ai: 'Classification',
  download: 'Downloads (Incomplete Detection)',
  web: 'Web UI',
  jellyfin: 'Jellyfin Integration',
  paths: 'Storage Paths',
  mcp: 'MCP Access Control',
}

const SECTION_ORDER = ['web', 'mcp', 'jellyfin', 'paths', 'download', 'ai']

function EyeIcon({ open }) {
  return open ? (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
      <circle cx="12" cy="12" r="3.5" />
    </svg>
  ) : (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17.94 17.94A10.94 10.94 0 0112 20C5 20 1 12 1 12a21.3 21.3 0 015.06-6.94" />
      <path d="M9.53 9.53A3.5 3.5 0 0012 15.5a3.5 3.5 0 002.47-5.97" />
      <path d="M14.12 14.12L9.88 9.88" />
      <path d="M1 1l22 22" />
      <path d="M10.58 10.58A3.5 3.5 0 0112 8.5a3.5 3.5 0 013.5 3.5c0 .62-.16 1.2-.44 1.71" opacity="0" />
    </svg>
  )
}

// Simpler closed-eye — eye with slash
function EyeOffIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9.88 9.88A3 3 0 0012 15a3 3 0 002.12-5.12" />
      <path d="M10.73 5.08A11 11 0 0112 4c7 0 11 8 11 8a18.2 18.2 0 01-2.16 3.19" />
      <path d="M14.12 14.12A3 3 0 019.88 9.88" />
      <path d="M2.9 6.1A11 11 0 001 12s4 8 11 8a9.6 9.6 0 005.39-1.61" />
      <path d="M1 1l22 22" />
    </svg>
  )
}

export default function SettingsPage() {
  const { state, actions } = useAppStore()
  const entries = state.adminEnv?.spec || []
  const pending = state.adminEnvPending || []
  const [draft, setDraft] = useState({})
  const [revealed, setRevealed] = useState({})
  const [oldPasswords, setOldPasswords] = useState({})
  const [oldRevealed, setOldRevealed] = useState({})
  const [recreateVars, setRecreateVars] = useState([])
  const [saving, setSaving] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [clearPanelPassword, setClearPanelPassword] = useState(false)
  const [clearMcpToken, setClearMcpToken] = useState(false)
  const originalRef = useRef(null)

  function parseBoolForDraft(e) {
    if (e.type !== 'bool') return e.effective
    const v = String(e.effective ?? '').toLowerCase()
    return v === 'true' || v === '1'
  }

  useEffect(() => {
    if (entries.length && originalRef.current === null) {
      const originals = {}
      const initial = {}
      entries.forEach((e) => {
        const val = e.type === 'bool' ? parseBoolForDraft(e) : (e.secret ? '' : e.effective)
        originals[e.key] = val
        initial[e.key] = val
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

  function validateValue(entry, value) {
    if (entry.secret || entry.type === 'bool' || entry.type === 'str') return null
    const text = String(value ?? '').trim()
    if (!text) return 'Required — enter a number'
    if (entry.type === 'int' && !/^-?\d+$/.test(text)) return 'Must be an integer'
    if (entry.type === 'float' && (Number.isNaN(Number(text)) || !Number.isFinite(Number(text)))) {
      return 'Must be a number'
    }
    return null
  }

  const draftErrors = useMemo(() => {
    const errors = {}
    entries.forEach((e) => {
      const err = validateValue(e, draft[e.key])
      if (err) errors[e.key] = err
    })
    return errors
  }, [entries, draft])

  function toggleReveal(key) {
    setRevealed((r) => ({ ...r, [key]: !r[key] }))
  }

  function toggleOldReveal(key) {
    setOldRevealed((r) => ({ ...r, [key]: !r[key] }))
  }

  function hasExistingPassword(entry) {
    if (!entry?.secret) return false
    const eff = entry.effective
    return eff === '********' || (eff && String(eff).trim() !== '')
  }

  function needsOldPassword(entry) {
    if (!hasExistingPassword(entry)) return false
    if (entry.key === 'JELLYSORT_MCP_TOKEN') return false
    if (entry.key === 'UI_PANEL_PASSWORD' && clearPanelPassword) return true
    const val = draft[entry.key]
    return !!(val && String(val).trim())
  }

  function countChanges() {
    const originals = originalRef.current || {}
    let changed = 0
    entries.forEach((e) => {
      const value = draft[e.key]
      if (e.key === 'UI_PANEL_PASSWORD' && clearPanelPassword) {
        const effective = entries.find((x) => x.key === 'UI_PANEL_PASSWORD')?.effective
        if (effective && String(effective).trim() && effective !== '********' ? true : effective === '********') {
          changed += 1
        } else if (effective === '********') {
          changed += 1
        }
      } else if (e.key === 'JELLYSORT_MCP_TOKEN' && clearMcpToken) {
        const effective = entries.find((x) => x.key === 'JELLYSORT_MCP_TOKEN')?.effective
        if (effective && String(effective).trim() && effective !== '********' ? true : effective === '********') {
          changed += 1
        } else if (effective === '********') {
          changed += 1
        }
      } else if (e.secret) {
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
    const oldForSave = {}
    let missingOld = null
    entries.forEach((e) => {
      const value = draft[e.key]
      if (e.key === 'UI_PANEL_PASSWORD' && clearPanelPassword) {
        updates[e.key] = ''
        if (hasExistingPassword(e)) {
          const old = oldPasswords[e.key] ?? ''
          if (!String(old).trim()) missingOld = e.key
          else oldForSave[e.key] = old
        }
      } else if (e.key === 'JELLYSORT_MCP_TOKEN' && clearMcpToken) {
        updates[e.key] = ''
      } else if (e.secret) {
        const text = String(value ?? '').trim()
        if (text) {
          if (e.key !== 'JELLYSORT_MCP_TOKEN' && hasExistingPassword(e)) {
            const old = oldPasswords[e.key] ?? ''
            if (!String(old).trim()) missingOld = e.key
            else oldForSave[e.key] = old
          }
          updates[e.key] = text
        }
      } else if (String(value ?? '') !== String(originals[e.key] ?? '')) {
        updates[e.key] = value ?? ''
      }
    })
    if (missingOld) {
      actions.toast(`Current password required to change ${missingOld}`, 'err')
      return
    }
    const keys = Object.keys(updates)
    if (!keys.length) {
      actions.toast('No changes to save', 'info')
      return
    }
    if (Object.keys(draftErrors).length) {
      actions.toast('Fix invalid values before saving: ' + Object.keys(draftErrors).join(', '), 'err')
      return
    }
    setSaving(true)
    try {
      const result = await actions.saveEnv(updates, oldForSave)
      actions.log('Settings saved: ' + keys.join(', '), 'good')
      const appliedLive = (result && result.appliedLive) || []
      const needs = (result && result.needsRecreate) || []
      if (needs.length) {
        setRecreateVars(needs)
        actions.toast(`Saved — ${needs.length} change${needs.length === 1 ? '' : 's'} need a container recreate`, 'warn')
      } else {
        setRecreateVars([])
        actions.toast(`${appliedLive.length || keys.length} setting${(appliedLive.length || keys.length) === 1 ? '' : 's'} applied live`, 'good')
      }
      originalRef.current = null
      const next = {}
      entries.forEach((e) => {
        next[e.key] = e.secret ? '' : draft[e.key]
      })
      originalRef.current = next
      // Clear secret fields in draft after save so Save count drops to 0 — otherwise typed password stays and counts as changed
      const cleared = {}
      let needsClear = false
      keys.forEach((k) => {
        const entry = entries.find((e) => e.key === k)
        if (entry?.secret) {
          cleared[k] = ''
          needsClear = true
        }
      })
      if (needsClear) {
        setDraft((d) => ({ ...d, ...cleared }))
      }
      setOldPasswords({})
      setOldRevealed({})
      setClearPanelPassword(false)
      setClearMcpToken(false)
    } catch (e) {
      /* error toast already shown by the store */
    } finally {
      setSaving(false)
    }
  }

  const PATH_KEYS = new Set(['DOWNLOAD_ROOTS', 'MOVIE_ROOTS', 'SERIES_ROOTS'])

  function renderInput(e) {
    if (e.key === 'SERIES_TITLE_ALIASES') {
      return <SeriesAliasField value={draft[e.key] ?? ''} onChange={(v) => setField(e.key, v)} />
    }
    if (PATH_KEYS.has(e.key)) {
      return <StoragePathField value={draft[e.key] ?? ''} onChange={(v) => setField(e.key, v)} label={e.key} />
    }
    if (e.options && Array.isArray(e.options)) {
      return (
        <select value={draft[e.key] ?? ''} onChange={(ev) => setField(e.key, ev.target.value)} aria-label={e.key}>
          {e.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt === '' ? '-- Disabled --' : opt}
            </option>
          ))}
        </select>
      )
    }
    if (e.type === 'bool') {
      const checked = draft[e.key] === true || String(draft[e.key]).toLowerCase() === 'true'
      return (
        <input
          type="checkbox"
          checked={checked}
          onChange={(ev) => setField(e.key, ev.target.checked)}
          aria-label={e.key}
        />
      )
    }
    if (e.secret) {
      const isPanelPassword = e.key === 'UI_PANEL_PASSWORD'
      const isMcpToken = e.key === 'JELLYSORT_MCP_TOKEN'
      const hasPassword = hasExistingPassword(e)
      const isClearing = (isPanelPassword && clearPanelPassword) || (isMcpToken && clearMcpToken)
      const isChanging = !isClearing && !!(draft[e.key] && String(draft[e.key]).trim())
      const needsOld = hasPassword && (isChanging || isClearing)
      if (isPanelPassword && clearPanelPassword) {
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
            <div className="secret-field">
              <input
                type="text"
                value=""
                placeholder="Will be cleared on save — direct login"
                disabled
                aria-label={e.key}
                style={{ opacity: 0.6 }}
              />
              <button type="button" className="small" onClick={() => setClearPanelPassword(false)} title="Undo clear">
                Undo Clear
              </button>
            </div>
            <div className="secret-field">
              <input
                type={oldRevealed[e.key] ? 'text' : 'password'}
                value={oldPasswords[e.key] ?? ''}
                placeholder="Enter current password to confirm clearing"
                onChange={(ev) => setOldPasswords((o) => ({ ...o, [e.key]: ev.target.value }))}
                aria-label={`${e.key}_old`}
              />
              <button type="button" className="small" onClick={() => toggleOldReveal(e.key)} title={oldRevealed[e.key] ? 'Hide password' : 'Reveal password'} aria-label={oldRevealed[e.key] ? 'Hide password' : 'Reveal password'} style={{ padding: '6px 8px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                {oldRevealed[e.key] ? <EyeOffIcon /> : <EyeIcon open />}
              </button>
            </div>
          </div>
        )
      }
      if (isMcpToken && clearMcpToken) {
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
            <div className="secret-field">
              <input
                type="text"
                value=""
                placeholder="Will be cleared on save — MCP will be open (no auth)"
                disabled
                aria-label={e.key}
                style={{ opacity: 0.6 }}
              />
              <button type="button" className="small" onClick={() => setClearMcpToken(false)} title="Undo clear">
                Undo Clear
              </button>
            </div>
          </div>
        )
      }
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
          <div className="secret-field">
            <input
              type={revealed[e.key] ? 'text' : 'password'}
              value={draft[e.key] ?? ''}
              placeholder={isPanelPassword ? (hasPassword ? '•••••••• (change or clear below)' : 'No password — direct login') : isMcpToken ? (hasPassword ? '•••••••• (change or clear below)' : 'Empty = MCP open (no auth)') : 'Leave blank to keep unchanged'}
              onChange={(ev) => {
                setField(e.key, ev.target.value)
                if (isPanelPassword && ev.target.value) setClearPanelPassword(false)
                if (isMcpToken && ev.target.value) setClearMcpToken(false)
              }}
              aria-label={e.key}
            />
            <button type="button" className="small" onClick={() => toggleReveal(e.key)} title={revealed[e.key] ? 'Hide password' : 'Reveal password'} aria-label={revealed[e.key] ? 'Hide password' : 'Reveal password'} style={{ padding: '6px 8px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              {revealed[e.key] ? <EyeOffIcon /> : <EyeIcon open />}
            </button>
            {isPanelPassword && hasPassword && (
              <button
                type="button"
                className="small"
                onClick={() => {
                  const next = !clearPanelPassword
                  setClearPanelPassword(next)
                  if (next) setField(e.key, '')
                }}
                title={clearPanelPassword ? 'Undo clear — keep existing password' : 'Remove password and allow direct login'}
                style={clearPanelPassword ? { background: 'var(--jf-warn-bg)', borderColor: 'var(--jf-warn)', color: 'var(--jf-warn)' } : undefined}
              >
                {clearPanelPassword ? 'Undo Clear' : 'Clear'}
              </button>
            )}
            {isMcpToken && hasPassword && (
              <button
                type="button"
                className="small"
                onClick={() => {
                  const next = !clearMcpToken
                  setClearMcpToken(next)
                  if (next) setField(e.key, '')
                }}
                title={clearMcpToken ? 'Undo clear — keep existing token' : 'Clear token and make MCP open (no auth)'}
                style={clearMcpToken ? { background: 'var(--jf-warn-bg)', borderColor: 'var(--jf-warn)', color: 'var(--jf-warn)' } : undefined}
              >
                {clearMcpToken ? 'Undo Clear' : 'Clear'}
              </button>
            )}
          </div>
          {needsOld && (
            <div className="secret-field">
              <input
                type={oldRevealed[e.key] ? 'text' : 'password'}
                value={oldPasswords[e.key] ?? ''}
                placeholder="Current password required to change"
                onChange={(ev) => setOldPasswords((o) => ({ ...o, [e.key]: ev.target.value }))}
                aria-label={`${e.key}_old`}
              />
              <button type="button" className="small" onClick={() => toggleOldReveal(e.key)} title={oldRevealed[e.key] ? 'Hide password' : 'Reveal password'} aria-label={oldRevealed[e.key] ? 'Hide password' : 'Reveal password'} style={{ padding: '6px 8px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                {oldRevealed[e.key] ? <EyeOffIcon /> : <EyeIcon open />}
              </button>
            </div>
          )}
        </div>
      )
    }
    return (
      <input
        type="text"
        inputMode={e.type === 'int' || e.type === 'float' ? 'decimal' : undefined}
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
        <div className="hint">
          Environment variables read from .env. Saving writes them to disk immediately.{' '}
          <button
            type="button"
            className="help-chip"
            onClick={() => setHelpOpen((o) => !o)}
            aria-expanded={helpOpen}
            title="What do live / recreate / pending mean?"
          >
            ?
          </button>
        </div>
      </div>

      {helpOpen && (
        <div className="panel help-box">
          <p>
            <strong>live</strong> — applied the moment you save; running components pick it up on their next read.
          </p>
          <p>
            <strong>recreate</strong> — baked into config snapshots at startup, so it needs{' '}
            <code>docker compose up -d --force-recreate</code> to take effect.
          </p>
          <p>
            <strong>pending</strong> — the saved value differs from what is currently effective (usually waiting for a
            recreate).
          </p>
        </div>
      )}

      {(() => {
        const mcpEntry = entries.find((e) => e.key === 'JELLYSORT_MCP_TOKEN')
        const panelEntry = entries.find((e) => e.key === 'UI_PANEL_PASSWORD')
        const isMcpInsecure = !mcpEntry || !mcpEntry.effective || String(mcpEntry.effective).trim() === ''
        const isPanelInsecure = !panelEntry || !panelEntry.effective || String(panelEntry.effective).trim() === ''
        if (!isMcpInsecure && !isPanelInsecure) return null
        const reasons = []
        if (isPanelInsecure) reasons.push('UI Panel password is not set — anyone with network access can open the web panel')
        if (isMcpInsecure) reasons.push('JellySort MCP token is not set — anyone with network access can call the MCP API')
        return (
          <div className="warn-box" role="alert" style={{ borderColor: 'var(--jf-warn)', background: 'var(--jf-warn-bg)', display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
            <span style={{ fontSize: '1.1rem', lineHeight: 1 }}>⚠️</span>
            <div>
              <strong>Unsecure — authentication disabled</strong>
              <ul style={{ margin: '6px 0 0 18px', padding: 0, fontSize: '0.85rem', lineHeight: 1.4 }}>
                {reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <div className="hint" style={{ marginTop: '6px', fontSize: '0.8rem' }}>
                Set a value for {isPanelInsecure && isMcpInsecure ? 'both' : isPanelInsecure ? 'UI_PANEL_PASSWORD' : 'JELLYSORT_MCP_TOKEN'} and save to secure this instance.
              </div>
            </div>
          </div>
        )
      })()}

      {recreateVars.length > 0 && (
        <div className="warn-box" role="alert">
          <strong>Recreate required</strong> — these changes need a container recreate to take effect:{' '}
          <code>{recreateVars.join(', ')}</code>
          <br />
          Run: <code>docker compose up -d --force-recreate</code>{' '}
          <button
            type="button"
            className="small"
            onClick={() => actions.copyText('docker compose up -d --force-recreate')}
          >
            Copy command
          </button>
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
        sections.map((section) => {
          const isDownload = section.id === 'download'
          const isJellyfin = section.id === 'jellyfin'
          const enableKey = isDownload ? 'ENABLE_INCOMPLETE_DOWNLOAD_DETECTION' : isJellyfin ? 'ENABLE_JELLYFIN_INTEGRATION' : null
          const enableEntry = enableKey ? section.items.find((e) => e.key === enableKey) : null
          const isEnabled = enableEntry ? (draft[enableKey] === true || String(draft[enableKey]).toLowerCase() === 'true') : true
          const sectionItems = section.items.filter((e) => {
            if (e.key === enableKey) return false
            if (!e.showWhen) return true
            return Object.entries(e.showWhen).every(([k, v]) => String(draft[k] ?? '') === String(v))
          })
          return (
            <section className={`panel ${enableEntry ? (isEnabled ? 'section-enabled' : 'section-disabled') : ''}`} key={section.id}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: sectionItems.length ? '12px' : 0 }}>
                <h2 style={{ margin: 0 }}>{section.label}</h2>
                {enableEntry && (
                  <label className="switch" title={isEnabled ? 'Enabled — click to disable' : 'Disabled — click to enable'} style={{ cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={(ev) => setField(enableKey, ev.target.checked)}
                      aria-label={enableKey}
                    />
                    <span className="switch-slider" />
                  </label>
                )}
              </div>
              {enableEntry && (
                <div className="hint" style={{ marginBottom: '12px', fontSize: '0.82rem', color: isEnabled ? 'var(--jf-success)' : 'var(--jf-text-muted)' }}>
                  {isEnabled ? '✓ Enabled — related settings below are active' : '○ Disabled — enable to configure ' + section.label.toLowerCase()}
                </div>
              )}
              <div className="env-grid">
                {enableEntry && (
                  <div className="env-row" key={enableEntry.key} style={{ display: 'none' }}>
                    {renderInput(enableEntry)}
                  </div>
                )}
                {sectionItems.map((e) => {
                const isPending = pending.includes(e.key)
                const isPathOrAlias = PATH_KEYS.has(e.key) || e.key === 'SERIES_TITLE_ALIASES'
                const isClearedPassword = e.key === 'UI_PANEL_PASSWORD' && clearPanelPassword
                const isClearedMcpToken = e.key === 'JELLYSORT_MCP_TOKEN' && clearMcpToken
                return (
                  <>
                    <div className="env-row" style={isPathOrAlias ? { flexDirection: 'column', alignItems: 'stretch', padding: '6px 10px', gap: '6px' } : undefined}>
                      <div className="env-meta" style={isPathOrAlias ? { width: '100%' } : undefined}>
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
                      <div className="env-input" style={isPathOrAlias ? { width: '100%', marginTop: '0', flex: 'none', minHeight: 'auto' } : undefined}>
                        {renderInput(e)}
                        {draftErrors[e.key] && (
                          <div className="env-error" role="alert">
                            {draftErrors[e.key]}
                          </div>
                        )}
                      </div>
                    </div>
                    {isClearedPassword && (
                      <div
                        style={{
                          gridColumn: '1 / -1',
                          margin: '-4px 0 8px 0',
                          padding: '8px 12px',
                          background: 'var(--jf-warn-bg)',
                          border: '1px solid var(--jf-warn)',
                          borderRadius: '6px',
                          color: 'var(--jf-warn)',
                          fontSize: '0.85rem',
                          textAlign: 'center',
                        }}
                      >
                        Password will be removed on save — panel will allow direct login.
                      </div>
                    )}
                    {isClearedMcpToken && (
                      <div
                        style={{
                          gridColumn: '1 / -1',
                          margin: '-4px 0 8px 0',
                          padding: '8px 12px',
                          background: 'var(--jf-warn-bg)',
                          border: '1px solid var(--jf-warn)',
                          borderRadius: '6px',
                          color: 'var(--jf-warn)',
                          fontSize: '0.85rem',
                          textAlign: 'center',
                        }}
                      >
                        Token will be removed on save — MCP will be open (no authentication).
                      </div>
                    )}
                  </>
                )
              })}
            </div>
            {section.id === 'download' && <IncompleteDownloadsNotes />}
            {section.id === 'jellyfin' && <JellyfinTest draft={draft} />}
            {section.id === 'mcp' && <McpClientSetup />}
          </section>
        )
      })
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

function IncompleteDownloadsNotes() {
  return (
    <div
      style={{
        marginTop: '12px',
        padding: '12px 14px',
        background: 'var(--jf-note-bg, rgba(127, 127, 127, 0.08))',
        border: '1px solid var(--jf-border, rgba(127, 127, 127, 0.35))',
        borderRadius: '8px',
        fontSize: '0.83rem',
        lineHeight: 1.5,
        color: 'var(--jf-text, inherit)',
      }}
    >
      <strong style={{ display: 'block', marginBottom: '6px' }}>How in-progress downloads are detected</strong>
      <p style={{ margin: '0 0 8px 0' }}>
        JellySort detects downloads that are still downloading by looking for the <em>incomplete-file marker</em> that
        your download client leaves next to the media file while it is still getting the data. Files with such a
        marker are skipped and never moved until they finish. When the download completes, the marker is stripped
        automatically and the file becomes eligible on the next scan.
      </p>
      <p style={{ margin: '0 0 8px 0' }}>
        For this to work, your download client must be configured to append a marker extension to incomplete files.
        Below are the markers used by the most common download clients — enable the matching option in your client so
        the marker is written while a download is in progress:
      </p>
      <ul style={{ margin: '0 0 10px 0', paddingLeft: '18px' }}>
        <li><strong>qBittorrent</strong> — <em>.!qB</em>: enable <em>"Append .!qB extension to incomplete files"</em> in <em>Tools &rarr; Options &rarr; BitTorrent</em>.</li>
        <li><strong>Transmission</strong> — <em>.part</em> (written automatically).</li>
        <li><strong>µTorrent</strong> — <em>.!ut</em>: enable <em>"Append .!ut to incomplete files"</em> in Preferences.</li>
        <li><strong>rTorrent</strong> — <em>.part</em> / <em>.partial</em> (written automatically).</li>
        <li><strong>Deluge</strong> — libtorrent <em>.parts</em> side files: enable <em>"Add .parts extension to incomplete files"</em>.</li>
      </ul>
      <p style={{ margin: 0 }}>
        Detection is case-insensitive and covers both appended suffixes (<em>.!qB</em>, <em>.!ut</em>, <em>.!bt</em>,{' '}
        <em>.part</em>, <em>.partial</em>, <em>.parts</em>) and prefixed markers (<em>incomplete.</em>). Toggle the
        switch above to turn skipping of in-progress downloads on or off.
      </p>
    </div>
  )
}

function JellyfinTest({ draft }) {
  const [result, setResult] = useState(null)
  const [testing, setTesting] = useState(false)
  async function doTest() {
    setTesting(true)
    setResult(null)
    try {
      const { apiPost } = await import('../api/apiClient.js')
      const r = await apiPost('/admin/test-jellyfin', { baseUrl: draft.JELLYFIN_BASE_URL, apiKey: draft.JELLYFIN_API_KEY })
      setResult({ ok: true, text: `Connected: ${r.serverName || 'Jellyfin'} ${r.version || ''}` })
    } catch (e) {
      setResult({ ok: false, text: e.message })
    } finally {
      setTesting(false)
    }
  }
  return (
    <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
      <button type="button" className="small" onClick={doTest} disabled={testing || !draft.JELLYFIN_BASE_URL?.trim()}>
        {testing ? 'Testing...' : 'Test Connection'}
      </button>
      {result && <span className={result.ok ? 'good-box' : 'env-error'} style={{ fontSize: '0.82rem', margin: 0 }}>{result.text}</span>}
    </div>
  )
}

function StoragePathField({ value, onChange, label }) {
  const [editOpen, setEditOpen] = useState(false)

  const pills = useMemo(() => {
    return String(value || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((entry) => {
        const [path, ...descParts] = entry.split('::')
        const desc = descParts.join('::').trim()
        return { path: path.trim(), description: desc, label: desc ? `${path.trim()} (${desc})` : path.trim() }
      })
  }, [value])

  return (
    <div style={{ width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: pills.length ? '8px' : '0' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', flex: 1, minWidth: 0 }}>
          {pills.length > 0 ? (
            pills.map((p) => (
              <span
                key={p.path}
                className="chip"
                title={p.label}
                style={{
                  fontFamily: 'monospace',
                  fontSize: '0.72rem',
                  background: 'var(--jf-surface-raised)',
                  border: '1px solid var(--jf-border)',
                  color: 'var(--jf-text)',
                  padding: '3px 8px',
                }}
              >
                {p.path}
                {p.description && <span style={{ color: 'var(--jf-text-muted)', marginLeft: '4px' }}>({p.description})</span>}
              </span>
            ))
          ) : (
            <span style={{ fontSize: '0.78rem', color: 'var(--jf-text-muted)', fontStyle: 'italic' }}>No folders configured</span>
          )}
        </div>
        <button
          type="button"
          className="small primary"
          onClick={() => setEditOpen(true)}
          title="Edit paths with browser"
          style={{ flex: 'none', padding: '4px 10px', fontSize: '0.78rem', alignSelf: 'center' }}
        >
          {pills.length ? 'Edit' : '+ Add'}
        </button>
      </div>
      {editOpen && (
        <StoragePathEditor
          label={label}
          value={value}
          onChange={onChange}
          onClose={() => setEditOpen(false)}
        />
      )}
    </div>
  )
}

function StoragePathEditor({ label, value, onChange, onClose }) {
  const [browserOpen, setBrowserOpen] = useState(false)
  const supportsDescription = label === 'MOVIE_ROOTS' || label === 'SERIES_ROOTS'

  const parsed = useMemo(() => {
    return String(value || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((entry) => {
        const [path, ...descParts] = entry.split('::')
        return { raw: entry, path: path.trim(), description: descParts.join('::').trim() }
      })
  }, [value])

  const paths = useMemo(() => parsed.map((p) => p.path), [parsed])

  function updateFromParsed(nextParsed) {
    const next = nextParsed.map((p) => (p.description ? `${p.path}::${p.description}` : p.path)).join(', ')
    onChange(next)
  }

  function removePath(targetPath) {
    updateFromParsed(parsed.filter((p) => p.path !== targetPath))
  }

  function updateDescription(targetPath, newDesc) {
    updateFromParsed(parsed.map((p) => (p.path === targetPath ? { ...p, description: newDesc } : p)))
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: '720px', width: '95%', maxHeight: '85vh', overflowY: 'auto' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <h3 style={{ margin: 0 }}>Edit {label}</h3>
          <button type="button" className="small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="hint" style={{ marginBottom: '12px', fontSize: '0.82rem' }}>
          Add, edit, or remove folders. For movie/series you can add an optional description like <code>/media/movies::Main</code>.
        </div>

        {parsed.length > 0 ? (
          <div style={{ marginBottom: '12px', overflowX: 'auto' }}>
            <table className="admin-table" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left', fontSize: '0.75rem' }}>Path</th>
                  {supportsDescription && <th style={{ textAlign: 'left', fontSize: '0.75rem', width: '220px' }}>Description</th>}
                  <th style={{ width: '70px' }}></th>
                </tr>
              </thead>
              <tbody>
                {parsed.map((p) => (
                  <tr key={p.path}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.85rem', color: 'var(--jf-text-strong)', maxWidth: '320px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.path}>
                      {p.path}
                    </td>
                    {supportsDescription && (
                      <td>
                        <input
                          type="text"
                          value={p.description}
                          onChange={(e) => updateDescription(p.path, e.target.value)}
                          placeholder="Description"
                          aria-label={`Description for ${p.path}`}
                          style={{ width: '100%', fontSize: '0.8rem', padding: '6px 10px', background: 'var(--jf-surface)' }}
                        />
                      </td>
                    )}
                    <td style={{ textAlign: 'right' }}>
                      <button type="button" className="small" aria-label={`Remove ${p.path}`} onClick={() => removePath(p.path)} title="Remove">
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div
            style={{
              background: 'var(--jf-bg-raised)',
              border: '1px dashed var(--jf-border)',
              borderRadius: '8px',
              padding: '16px',
              textAlign: 'center',
              marginBottom: '12px',
              color: 'var(--jf-text-muted)',
              fontSize: '0.85rem',
            }}
          >
            No folders configured yet.
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
          <button type="button" className="small primary" onClick={() => setBrowserOpen(true)}>
            + Browse & Add Folder
          </button>
          <span style={{ fontSize: '0.78rem', color: 'var(--jf-text-faint)', alignSelf: 'center' }}>{parsed.length} folder{parsed.length === 1 ? '' : 's'}</span>
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label style={{ fontSize: '0.82rem', color: 'var(--jf-text-muted)', display: 'block', marginBottom: '4px' }}>Raw value (advanced)</label>
          <input
            type="text"
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder="/media/downloads, /media/movies"
            aria-label={label}
            style={{ width: '100%', fontSize: '0.78rem', fontFamily: 'monospace' }}
          />
        </div>

        {browserOpen && (
          <StoragePathBrowser
            label={label}
            existingPaths={paths}
            onAdd={(newPath) => {
              if (paths.includes(newPath)) return
              onChange([value, newPath].filter(Boolean).join(', ').replace(/^, /, ''))
            }}
            onClose={() => setBrowserOpen(false)}
          />
        )}

        <div className="modal-actions">
          <button type="button" className="primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}

function StoragePathBrowser({ label, existingPaths, onAdd, onClose }) {
  const [cwd, setCwd] = useState('/')
  const [entries, setEntries] = useState([])
  const [parent, setParent] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    apiGet(`/setup/fs?path=${encodeURIComponent(cwd)}`)
      .then((res) => {
        if (!alive) return
        setEntries(res.entries || [])
        setParent(res.parent)
        setError(null)
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [cwd])

  function handleSelect(path) {
    if (existingPaths.includes(path)) return
    onAdd(path, '')
    onClose()
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: '720px', width: '95%' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <h3 style={{ margin: 0 }}>Browse folders — {label}</h3>
          <button type="button" className="small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="wiz-crumbs" style={{ marginBottom: '10px' }}>
          <code style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cwd}</code>
          {parent && (
            <button type="button" className="small" onClick={() => setCwd(parent)}>
              Up
            </button>
          )}
        </div>

        {error && <div className="env-error" style={{ marginBottom: '8px' }}>{error}</div>}

        {loading ? (
          <div className="hint" style={{ padding: '16px 0', textAlign: 'center' }}>
            <span className="spinner" /> Loading...
          </div>
        ) : (
          <ul className="wiz-dirs" style={{ maxHeight: '320px' }}>
            {entries.map((entry) => {
              const alreadyAdded = existingPaths.includes(entry.path)
              return (
                <li key={entry.path} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <button
                    type="button"
                    className="linklike small"
                    onClick={() => setCwd(entry.path)}
                    style={{ flex: 1, textAlign: 'left', fontFamily: 'monospace' }}
                  >
                    {entry.name}/
                  </button>
                  <button
                    type="button"
                    className="small primary"
                    onClick={() => handleSelect(entry.path)}
                    disabled={alreadyAdded}
                    title={alreadyAdded ? 'Already added' : `Select ${entry.path}`}
                  >
                    {alreadyAdded ? 'Added' : 'Select'}
                  </button>
                </li>
              )
            })}
            {!entries.length && !error && <li className="hint">No subfolders here.</li>}
          </ul>
        )}

        <div className="hint" style={{ marginTop: '10px', fontSize: '0.78rem' }}>
          Click a folder name to drill in, then <strong>Select</strong> to add it. Add a description afterwards in the table.
        </div>

        <div className="modal-actions">
          <button type="button" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}

function McpClientSetup() {
  const [open, setOpen] = useState(false)
  const mcpUrl = typeof window !== 'undefined' ? window.location.origin + '/mcp' : 'http://<host>:18328/mcp'
  return (
    <div style={{ marginTop: '12px' }}>
      <button
        type="button"
        className="small"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title={open ? 'Hide client setup' : 'Show how to configure an MCP client'}
        style={{ fontSize: '0.82rem' }}
      >
        <span style={{ display: 'inline-block', transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'rotate(0deg)', marginRight: '6px' }}>▸</span>
        {open ? 'Hide client setup' : 'Show client setup'}
      </button>
      {open && (
        <div style={{ marginTop: '8px', padding: '10px 12px', background: 'var(--jf-bg-raised)', border: '1px solid var(--jf-border-soft)', borderRadius: '6px' }}>
          <div className="hint" style={{ fontSize: '0.82rem' }}>
            When a token is set, send it with every MCP request as <code>Authorization: Bearer &lt;token&gt;</code> or <code>X-API-Key: &lt;token&gt;</code>. When empty, MCP is open (no header required).
          </div>
          <pre className="code-block" style={{ marginTop: '8px', fontSize: '0.78rem' }}>{`{
  "mcpServers": {
    "jellysort": {
      "type": "remote",
      "url": "${mcpUrl}",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}`}</pre>
          <div className="hint" style={{ fontSize: '0.78rem', marginTop: '6px' }}>Example opencode remote MCP config. Replace &lt;token&gt; with the value of JELLYSORT_MCP_TOKEN.</div>
        </div>
      )}
    </div>
  )
}

function SeriesAliasField({ value, onChange }) {
  const [editOpen, setEditOpen] = useState(false)

  const pills = useMemo(() => {
    return String(value || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((entry) => {
        const [alias, ...rest] = entry.split('::')
        const canonical = rest.join('::').trim()
        return { alias: alias.trim(), canonical, label: canonical ? `${alias.trim()} (${canonical})` : alias.trim() }
      })
  }, [value])

  return (
    <div style={{ width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', flex: 1, minWidth: 0 }}>
          {pills.length > 0 ? (
            pills.map((p, idx) => (
              <span
                key={`${p.alias}-${idx}`}
                className="chip"
                title={p.label}
                style={{
                  fontSize: '0.72rem',
                  background: 'var(--jf-surface-raised)',
                  border: '1px solid var(--jf-border)',
                  color: 'var(--jf-text)',
                  padding: '3px 8px',
                }}
              >
                {p.alias}
                {p.canonical && <span style={{ color: 'var(--jf-text-muted)', marginLeft: '4px' }}>({p.canonical})</span>}
              </span>
            ))
          ) : (
            <span style={{ fontSize: '0.78rem', color: 'var(--jf-text-muted)', fontStyle: 'italic' }}>No aliases yet</span>
          )}
        </div>
        <button
          type="button"
          className="small primary"
          onClick={() => setEditOpen(true)}
          title="Edit aliases visually"
          style={{ flex: 'none', padding: '4px 10px', fontSize: '0.78rem', alignSelf: 'center' }}
        >
          {pills.length ? 'Edit' : '+ Add'}
        </button>
      </div>
      {editOpen && <SeriesAliasEditor value={value} onChange={onChange} onClose={() => setEditOpen(false)} />}
    </div>
  )
}

function SeriesAliasEditor({ value, onChange, onClose }) {
  const [alias, setAlias] = useState('')
  const [canonical, setCanonical] = useState('')

  const parsed = useMemo(() => {
    return String(value || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
      .map((entry) => {
        const [a, ...rest] = entry.split('::')
        return { raw: entry, alias: a.trim(), canonical: rest.join('::').trim() }
      })
  }, [value])

  function updateFromParsed(nextParsed) {
    const next = nextParsed.map((p) => `${p.alias}::${p.canonical}`).join(', ')
    onChange(next)
  }

  function removeAt(idx) {
    updateFromParsed(parsed.filter((_, i) => i !== idx))
  }

  function addCurrent() {
    const a = alias.trim()
    const c = canonical.trim()
    if (!a || !c) return
    if (parsed.some((p) => p.alias === a)) return
    updateFromParsed([...parsed, { alias: a, canonical: c }])
    setAlias('')
    setCanonical('')
  }

  function updateAlias(idx, newAlias) {
    updateFromParsed(parsed.map((p, i) => (i === idx ? { ...p, alias: newAlias } : p)))
  }

  function updateCanonical(idx, newCanonical) {
    updateFromParsed(parsed.map((p, i) => (i === idx ? { ...p, canonical: newCanonical } : p)))
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: '720px', width: '95%', maxHeight: '85vh', overflowY: 'auto' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
          <h3 style={{ margin: 0 }}>Edit Series Title Aliases</h3>
          <button type="button" className="small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="hint" style={{ marginBottom: '12px', fontSize: '0.82rem' }}>
          Map release titles to library folder names. Example: <code>Shingeki no Kyojin::Attack on Titan</code>
        </div>

        {parsed.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '12px' }}>
            <div style={{ display: 'flex', gap: '8px', padding: '0 4px', fontSize: '0.72rem', fontWeight: 600, color: 'var(--jf-text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              <span style={{ flex: '1 1 0' }}>Release title (alias)</span>
              <span style={{ flex: '1 1 0' }}>Library folder (canonical)</span>
              <span style={{ width: '40px' }} />
            </div>
            {parsed.map((p, idx) => (
              <div
                key={`${p.alias}-${idx}`}
                style={{
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'center',
                  background: 'var(--jf-bg-raised)',
                  border: '1px solid var(--jf-border-soft)',
                  borderRadius: '6px',
                  padding: '8px 10px',
                }}
              >
                <input
                  type="text"
                  value={p.alias}
                  onChange={(e) => updateAlias(idx, e.target.value)}
                  placeholder="e.g. Kimetsu no Yaiba"
                  aria-label={`Alias ${idx}`}
                  style={{ flex: '1 1 0', fontSize: '0.85rem' }}
                />
                <span style={{ color: 'var(--jf-text-faint)', fontSize: '0.9rem' }}>→</span>
                <input
                  type="text"
                  value={p.canonical}
                  onChange={(e) => updateCanonical(idx, e.target.value)}
                  placeholder="e.g. Demon Slayer"
                  aria-label={`Canonical ${idx}`}
                  style={{ flex: '1 1 0', fontSize: '0.85rem' }}
                />
                <button type="button" className="small" onClick={() => removeAt(idx)} aria-label={`Remove alias ${p.alias}`} title="Remove">
                  Remove
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div
            style={{
              background: 'var(--jf-bg-raised)',
              border: '1px dashed var(--jf-border)',
              borderRadius: '8px',
              padding: '14px',
              textAlign: 'center',
              marginBottom: '12px',
              color: 'var(--jf-text-muted)',
              fontSize: '0.85rem',
            }}
          >
            No aliases yet.
            <br />
            <span style={{ fontSize: '0.78rem' }}>Add one below — useful for Japanese titles vs English folder names.</span>
          </div>
        )}

        <div
          style={{
            display: 'flex',
            gap: '8px',
            alignItems: 'center',
            background: 'var(--jf-bg-raised)',
            border: '1px solid var(--jf-border-soft)',
            borderRadius: '8px',
            padding: '10px 12px',
            marginBottom: '12px',
          }}
        >
          <input
            type="text"
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="Release title"
            aria-label="New alias"
            style={{ flex: '1 1 0', fontSize: '0.85rem' }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addCurrent()
              }
            }}
          />
          <span style={{ color: 'var(--jf-text-faint)' }}>→</span>
          <input
            type="text"
            value={canonical}
            onChange={(e) => setCanonical(e.target.value)}
            placeholder="Folder name"
            aria-label="New canonical"
            style={{ flex: '1 1 0', fontSize: '0.85rem' }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                addCurrent()
              }
            }}
          />
          <button type="button" className="small primary" onClick={addCurrent} disabled={!alias.trim() || !canonical.trim()} style={{ flex: 'none' }}>
            Add Alias
          </button>
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label style={{ fontSize: '0.82rem', color: 'var(--jf-text-muted)', display: 'block', marginBottom: '4px' }}>Raw value</label>
          <input
            type="text"
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder="alias1::canonical1, alias2::canonical2"
            aria-label="SERIES_TITLE_ALIASES"
            style={{ width: '100%', fontSize: '0.78rem', fontFamily: 'monospace' }}
          />
        </div>

        <div className="modal-actions">
          <button type="button" className="primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
