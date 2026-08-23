import { useEffect, useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { formatDateTime } from '../utils/format.js'
import { apiGet } from '../api/apiClient.js'

export default function ApiKeysPage() {
  const { state, actions } = useAppStore()
  const keys = state.adminKeys || []
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [createdKey, setCreatedKey] = useState(null)
  const [copiedId, setCopiedId] = useState(null)
  const [revealingId, setRevealingId] = useState(null)
  const mcpUrl = (typeof window !== 'undefined' ? window.location.origin : 'http://<host>:18328') + '/mcp'

  // Load env if not already loaded so we can check MCP_ALLOW_UNAUTHENTICATED
  useEffect(() => {
    if (!state.adminEnv && !state.adminLoading) {
      actions.loadEnv()
    }
  }, [state.adminEnv, state.adminLoading])

  const mcpAllowUnauth = (() => {
    const entry = (state.adminEnv?.spec || []).find((e) => e.key === 'MCP_ALLOW_UNAUTHENTICATED')
    if (!entry) return null
    // effective is string "true"/"false" from list_env
    const v = String(entry.effective || '').toLowerCase()
    return v === 'true' || v === '1' || v === 'yes'
  })()

  function openCreate() {
    setName('')
    setCreateOpen(true)
  }

  function closeCreate() {
    if (!busy) setCreateOpen(false)
  }

  async function onCreate(e) {
    e.preventDefault()
    if (!name.trim() || busy) return
    setBusy(true)
    try {
      const result = await actions.createApiKey({ name: name.trim() })
      setCreateOpen(false)
      setCreatedKey(result)
      setName('')
    } catch (err) {
      /* error toast already shown */
    } finally {
      setBusy(false)
    }
  }

  function onDelete(key) {
    const ok = window.confirm('Delete the API key "' + key.name + '" permanently? Clients using it will lose access.')
    if (!ok) return
    actions.deleteApiKey(key.id)
  }

  async function copyKey(keyId, name) {
    setRevealingId(keyId)
    try {
      const res = await apiGet('/admin/api-keys/' + keyId + '/reveal')
      const fullKey = res.key
      await actions.copyText(fullKey)
      setCopiedId(keyId)
      setTimeout(() => setCopiedId(null), 2000)
    } catch (err) {
      actions.toast(err.message || 'Key not revealable — recreate it', 'err')
    } finally {
      setRevealingId(null)
    }
  }

  return (
    <div className="admin-page">
      <div className="admin-header">
        <h2>API Keys</h2>
        <div className="hint">
          Keys are used to authenticate MCP clients on {mcpUrl} when <code>MCP_ALLOW_UNAUTHENTICATED=false</code>.
          Full keys are stored and can be copied anytime.
        </div>
      </div>

      {mcpAllowUnauth === true && (
        <div className="panel" style={{ background: 'var(--jf-primary-dim)', borderColor: 'var(--jf-primary)', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
          <div style={{ fontSize: '1.2rem', lineHeight: '1' }}>ℹ️</div>
          <div>
            <strong>Authentication is currently disabled</strong>
            <div className="hint" style={{ marginTop: '4px' }}>
              <code>MCP_ALLOW_UNAUTHENTICATED=true</code> — MCP allows unauthenticated requests, so API keys will not be enforced.
              Set it to <code>false</code> in <a href="/settings" onClick={(e) => { e.preventDefault(); actions.setPage('settings') }} style={{ color: 'var(--jf-primary-hover)' }}>Settings</a> and recreate the container to require authentication.
            </div>
          </div>
        </div>
      )}

      <section className="panel">
        <div className="keys-header">
          <h2>Keys</h2>
          <button type="button" className="primary" onClick={openCreate}>
            Create Key
          </button>
        </div>
        {state.adminLoading && !keys.length ? (
          <div>
            <span className="spinner" /> Loading keys...
          </div>
        ) : keys.length === 0 ? (
          <div className="hint">No API keys yet. Click "Create Key" to let MCP clients authenticate.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table apikeys-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>API Key</th>
                  <th>Created</th>
                  <th>Last Used</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id}>
                    <td>
                      <span className="key-name">{key.name}</span>
                    </td>
                    <td>
                      <code className="key-masked" title={key.key_prefix + '...' + (key.key_suffix || '')}>
                        {key.key_prefix}
                        <span className="key-mask">{"•".repeat(8)}</span>
                        {key.key_suffix || ''}
                      </code>
                    </td>
                    <td className="key-created">{formatDateTime(key.created_at)}</td>
                    <td className={'key-used' + (key.last_used_at ? '' : ' never')}>
                      {key.last_used_at ? 'Last used ' + formatDateTime(key.last_used_at) : 'Never used'}
                    </td>
                    <td style={{ whiteSpace: 'nowrap', display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        className="small"
                        onClick={() => copyKey(key.id, key.name)}
                        disabled={revealingId === key.id}
                        title="Copy full key to clipboard"
                      >
                        {revealingId === key.id ? '...' : copiedId === key.id ? 'Copied!' : 'Copy'}
                      </button>
                      <button type="button" className="small danger" onClick={() => onDelete(key)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Client setup</h2>
        <div className="hint">Send the key with every MCP request:</div>
        <pre className="code-block">{'Authorization: Bearer <key>'}</pre>
        <div className="hint">
          Or use the <code>X-API-Key</code> header. Example opencode remote MCP config:
        </div>
        <pre className="code-block">{`{
  "mcpServers": {
    "jellysort": {
      "type": "remote",
      "url": "${mcpUrl}",
      "headers": { "Authorization": "Bearer <key>" }
    }
  }
}`}</pre>
      </section>

      {createOpen && (
        <div className="modal-overlay" onClick={closeCreate}>
          <div className="modal modal-sm" onClick={(e) => e.stopPropagation()}>
            <h3>Create API key</h3>
            <form onSubmit={onCreate}>
              <label htmlFor="new-key-name">Key name</label>
              <input
                id="new-key-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. opencode on laptop"
                autoFocus
              />
              <div className="modal-actions">
                <button type="button" onClick={closeCreate} disabled={busy}>
                  Cancel
                </button>
                <button type="submit" className="primary" disabled={!name.trim() || busy}>
                  {busy ? 'Creating...' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {createdKey && (
        <div className="modal-overlay" onClick={() => setCreatedKey(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Key created — store it now</h3>
            <p className="hint">
              The full key can be copied anytime from the table below. If you lose it, delete and recreate.
            </p>
            <div className="key-display">
              <code>{createdKey.key}</code>
              <button type="button" className="small" onClick={() => actions.copyText(createdKey.key)}>
                Copy
              </button>
            </div>
            <div className="modal-actions">
              <button type="button" className="primary" onClick={() => setCreatedKey(null)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
