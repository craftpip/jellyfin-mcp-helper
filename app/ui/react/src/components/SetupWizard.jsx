import { useEffect, useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { apiGet, apiPost } from '../api/apiClient.js'

const STEPS = ['Downloads', 'Movies', 'Series', 'Jellyfin', 'Review']

export default function SetupWizard() {
  const { actions } = useAppStore()
  const [step, setStep] = useState(0)
  const [downloadRoots, setDownloadRoots] = useState([])
  const [movieRoots, setMovieRoots] = useState([])
  const [seriesRoots, setSeriesRoots] = useState([])
  const [jellyfinUrl, setJellyfinUrl] = useState('')
  const [jellyfinKey, setJellyfinKey] = useState('')
  const [jfResult, setJfResult] = useState(null)
  const [saving, setSaving] = useState(false)

  function skipSetup() {
    actions.dismissSetup()
  }

  return (
    <div className="admin-page wizard" data-testid="setup-wizard">
      <div className="panel">
        <h2>Welcome to JellySort</h2>
        <p className="hint">
          Point JellySort at your folders to get started. You can change everything later in Settings.
        </p>
        <ol className="wiz-steps">
          {STEPS.map((label, i) => (
            <li key={label} className={i === step ? 'active' : i < step ? 'done' : ''}>
              {label}
            </li>
          ))}
        </ol>

        {step < 3 && (
          <FolderPickerStep
            kind={STEPS[step].toLowerCase()}
            roots={[downloadRoots, movieRoots, seriesRoots][step]}
            onChange={(next) => [setDownloadRoots, setMovieRoots, setSeriesRoots][step](next)}
          />
        )}

        {step === 3 && (
          <div className="wiz-step-body">
            <h3>Jellyfin (optional)</h3>
            <p className="hint">Used to refresh libraries automatically after files are moved.</p>
            <div className="env-row">
              <div className="env-meta"><div className="env-key">JELLYFIN_BASE_URL</div></div>
              <div className="env-input">
                <input
                  value={jellyfinUrl}
                  placeholder="http://jellyfin.local:8096"
                  onChange={(e) => setJellyfinUrl(e.target.value)}
                  aria-label="Jellyfin base URL"
                />
              </div>
            </div>
            <div className="env-row">
              <div className="env-meta"><div className="env-key">JELLYFIN_API_KEY</div></div>
              <div className="env-input">
                <input
                  type="password"
                  value={jellyfinKey}
                  placeholder="Dashboard > API Keys"
                  onChange={(e) => setJellyfinKey(e.target.value)}
                  aria-label="Jellyfin API key"
                />
              </div>
            </div>
            <button
              type="button"
              className="small"
              onClick={async () => {
                setJfResult(null)
                try {
                  const res = await apiPost('/admin/test-jellyfin', { baseUrl: jellyfinUrl, apiKey: jellyfinKey })
                  setJfResult({ ok: true, text: `Connected: ${res.serverName || 'Jellyfin'} ${res.version || ''}` })
                } catch (e) {
                  setJfResult({ ok: false, text: e.message })
                }
              }}
              disabled={!jellyfinUrl.trim()}
            >
              Test connection
            </button>
            {jfResult && (
              <div className={jfResult.ok ? 'good-box' : 'env-error'} role="alert">
                {jfResult.text}
              </div>
            )}
          </div>
        )}

        {step === 4 && (
          <div className="wiz-step-body">
            <h3>Review</h3>
            <RootSummary label="Download roots" roots={downloadRoots} />
            <RootSummary label="Movie roots" roots={movieRoots} />
            <RootSummary label="Series roots" roots={seriesRoots} />
            <p className="hint">
              Jellyfin: {jellyfinUrl.trim() ? jellyfinUrl.trim() : 'not configured'}
            </p>
          </div>
        )}

        <div className="admin-footer wiz-nav">
          <button type="button" className="small linklike" onClick={skipSetup}>
            Skip setup
          </button>
          <div className="spacer" />
          {step > 0 && (
            <button type="button" onClick={() => setStep((s) => s - 1)}>
              Back
            </button>
          )}
          {step >= 0 && step <= 3 && (
            <button type="button" onClick={() => setStep((s) => s + 1)}>
              Next
            </button>
          )}
          {step === 4 && (
            <button
              type="button"
              className="primary"
              disabled={saving}
              onClick={async () => {
                setSaving(true)
                try {
                  const updates = {
                    DOWNLOAD_ROOTS: downloadRoots.join(','),
                    MOVIE_ROOTS: movieRoots.join(','),
                    SERIES_ROOTS: seriesRoots.join(','),
                  }
                  if (jellyfinUrl.trim()) {
                    updates.JELLYFIN_BASE_URL = jellyfinUrl.trim()
                    if (jellyfinKey.trim()) updates.JELLYFIN_API_KEY = jellyfinKey.trim()
                  }
                  await apiPost('/admin/env', { updates })
                  actions.log('Setup complete — saved media roots', 'good')
                  window.location.reload()
                } catch (e) {
                  actions.toast('Failed to save setup: ' + e.message, 'err')
                  setSaving(false)
                }
              }}
            >
              {saving ? 'Saving...' : 'Finish setup'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function RootSummary({ label, roots }) {
  return (
    <div className="wiz-summary-row">
      <strong>{label}:</strong> {roots.length ? roots.join(', ') : <em>none</em>}
    </div>
  )
}

function FolderPickerStep({ kind, roots, onChange }) {
  const [cwd, setCwd] = useState('/')
  const [entries, setEntries] = useState([])
  const [parent, setParent] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    apiGet(`/setup/fs?path=${encodeURIComponent(cwd)}`)
      .then((res) => {
        if (!alive) return
        setEntries(res.entries || [])
        setParent(res.parent)
        setError(null)
      })
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [cwd])

  function toggle(path) {
    onChange(roots.includes(path) ? roots.filter((r) => r !== path) : [...roots, path])
  }

  return (
    <div className="wiz-step-body">
      <h3>Pick your {kind} folders</h3>
      <div className="wiz-crumbs">
        <code>{cwd}</code>
        {parent && (
          <button type="button" className="small" onClick={() => setCwd(parent)}>
            Up
          </button>
        )}
      </div>
      {error && <div className="env-error">{error}</div>}
      <ul className="wiz-dirs">
        {entries.map((entry) => (
          <li key={entry.path}>
            <button type="button" className="linklike small" onClick={() => setCwd(entry.path)}>
              {entry.name}/
            </button>
            <button
              type="button"
              className="small"
              onClick={() => toggle(entry.path)}
            >
              {roots.includes(entry.path) ? 'Selected' : 'Select'}
            </button>
          </li>
        ))}
        {!entries.length && !error && <li className="hint">No subfolders here.</li>}
      </ul>
      {roots.length > 0 && (
        <div className="wiz-selected">
          {roots.map((path) => (
            <span className="chip" key={path}>
              {path}{' '}
              <button type="button" aria-label={`Remove ${path}`} onClick={() => toggle(path)}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
