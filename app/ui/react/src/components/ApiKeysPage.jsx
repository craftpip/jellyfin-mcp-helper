import { useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { formatDateTime } from '../utils/format.js'

export default function ApiKeysPage() {
  const { state, actions } = useAppStore()
  const keys = state.adminKeys || []
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [createdKey, setCreatedKey] = useState(null)
  const mcpUrl = (typeof window !== 'undefined' ? window.location.origin : 'http://<host>:18328') + '/mcp'

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

  return (
    <div className="admin-page">
      <div className="admin-header">
        <h2>API Keys</h2>
        <div className="hint">
          Keys are used to authenticate MCP clients on {mcpUrl} when <code>MCP_ALLOW_UNAUTHENTICATED=false</code>.
          Full keys are only stored hashed and shown once at creation.
        </div>
      </div>

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
          <div className="keys-list">
            {keys.map((key) => (
              <div className="keys-row" key={key.id}>
                <div className="keys-row-top">
                  <span className="key-name">{key.name}</span>
                  <span className="key-created">Created {formatDateTime(key.created_at)}</span>
                  <button type="button" className="small danger" onClick={() => onDelete(key)}>
                    Delete
                  </button>
                </div>
                <div className="keys-row-bottom">
                  <code className="key-masked" title="Only the start and end of the key are shown">
                    {key.key_prefix}
                    {'*'.repeat(6)}
                    {key.key_suffix || ''}
                  </code>
                  <span className={'key-used' + (key.last_used_at ? '' : ' never')}>
                    {key.last_used_at ? 'Last used ' + formatDateTime(key.last_used_at) : 'Never used'}
                  </span>
                </div>
              </div>
            ))}
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
              The full key is only shown this once. It is stored hashed on disk and cannot be retrieved again. If you
              lose it, delete this key and create a new one.
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
