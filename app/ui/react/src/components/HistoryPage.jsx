import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/apiClient.js'
import { useAppStore } from '../store/AppStore.jsx'

export default function HistoryPage() {
  const { actions } = useAppStore()
  const [groups, setGroups] = useState([])
  const [scans, setScans] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState({})
  const [editing, setEditing] = useState({}) // history_id -> {confirmId -> newTarget}
  const [busy, setBusy] = useState(null)

  async function load() {
    setLoading(true)
    try {
      const [res, scanRes] = await Promise.all([
        apiGet('/history?limit=50').catch(() => ({ groups: [] })),
        apiGet('/scans/history?limit=50').catch(() => ({ history: [] })),
      ])
      setGroups(res.groups || [])
      setScans(scanRes.history || [])
    } catch (e) {
      actions.toast('Failed to load history: ' + e.message, 'err')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function toggleGroup(id) {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  async function handleUndo(group) {
    if (!window.confirm(`Undo ${group.group_title}? This will move ${group.items.length} file(s) back to their source locations.`)) return
    setBusy(group.history_id)
    try {
      const res = await apiPost(`/history/${group.history_id}/undo`)
      actions.toast(`Undone ${res.restored} file(s)`, res.restored ? 'good' : 'warn')
      await load()
    } catch (e) {
      actions.toast('Undo failed: ' + e.message, 'err')
    } finally {
      setBusy(null)
    }
  }

  function handleEditChange(historyId, confirmId, newTarget) {
    setEditing((prev) => ({
      ...prev,
      [historyId]: { ...(prev[historyId] || {}), [confirmId]: newTarget },
    }))
  }

  async function handleRetarget(group) {
    const edits = editing[group.history_id] || {}
    const updates = Object.entries(edits)
      .filter(([, v]) => v && String(v).trim())
      .map(([confirmId, newTarget]) => ({ confirmId, newTarget: String(newTarget).trim() }))
    if (!updates.length) {
      actions.toast('No changes to save', 'info')
      return
    }
    setBusy(group.history_id)
    try {
      const res = await apiPost(`/history/${group.history_id}/retarget`, { updates })
      actions.toast(`Moved ${res.moved} file(s) to new locations`, 'good')
      setEditing((prev) => ({ ...prev, [group.history_id]: {} }))
      await load()
    } catch (e) {
      actions.toast('Retarget failed: ' + e.message, 'err')
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="panel">
        <span className="spinner" /> Loading history...
      </div>
    )
  }

  if (!groups.length && !scans.length) {
    return (
      <div className="panel">
        <h2>History</h2>
        <div className="hint">No confirms yet — scan and confirm a group to see it here. No scans in history either.</div>
      </div>
    )
  }

  if (!groups.length && scans.length) {
    return (
      <div className="admin-page" style={{ maxWidth: 'none' }}>
        <div className="admin-header">
          <h2>History</h2>
          <div className="hint">No confirms yet — scan and confirm a group to see confirm history. Below are your past scans (migrated from files).</div>
        </div>
        <div className="panel" style={{ padding: '12px' }}>
          <h3 style={{ margin: '0 0 8px 0' }}>Scans history ({scans.length})</h3>
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Scan ID</th>
                  <th>Date</th>
                  <th>Movies</th>
                  <th>Series</th>
                  <th>Skipped</th>
                  <th>To move</th>
                </tr>
              </thead>
              <tbody>
                {scans.map((s) => (
                  <tr key={s.scan_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{s.scan_id.slice(0, 8)}</td>
                    <td style={{ fontSize: '0.78rem' }}>{s.saved_at ? new Date(s.saved_at).toLocaleString() : ''}</td>
                    <td>{s.movies ?? ''}</td>
                    <td>{s.series ?? ''}</td>
                    <td>{s.skipped ?? ''}</td>
                    <td>{s.action_required ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="admin-page" style={{ maxWidth: 'none' }}>
      <div className="admin-header">
        <h2>History</h2>
        <div className="hint">Every confirmed group is saved here. You can review, undo, or rename folders and move again. The full path trail is kept for display.</div>
      </div>

      {scans.length > 0 && (
        <div className="panel" style={{ padding: '12px', marginBottom: 12 }}>
          <h3 style={{ margin: '0 0 8px 0' }}>Scans history ({scans.length}) — migrated from files</h3>
          <div style={{ overflowX: 'auto' }}>
            <table className="admin-table" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Scan ID</th>
                  <th>Date</th>
                  <th>Movies</th>
                  <th>Series</th>
                  <th>Skipped</th>
                  <th>To move</th>
                </tr>
              </thead>
              <tbody>
                {scans.map((s) => (
                  <tr key={s.scan_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}>{s.scan_id.slice(0, 8)}</td>
                    <td style={{ fontSize: '0.78rem' }}>{s.saved_at ? new Date(s.saved_at).toLocaleString() : ''}</td>
                    <td>{s.movies ?? ''}</td>
                    <td>{s.series ?? ''}</td>
                    <td>{s.skipped ?? ''}</td>
                    <td>{s.action_required ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {groups.map((group) => {
        const isExpanded = !!expanded[group.history_id]
        const groupEdits = editing[group.history_id] || {}
        const hasEdits = Object.values(groupEdits).some((v) => v && String(v).trim())
        return (
          <div key={group.history_id} className="panel" style={{ padding: '12px' }}>
            <div
              style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer' }}
              onClick={() => toggleGroup(group.history_id)}
            >
              <span style={{ fontSize: '0.8rem', color: 'var(--jf-text-muted)' }}>{isExpanded ? '▼' : '▶'}</span>
              <strong style={{ flex: 1 }}>{group.group_title}</strong>
              <span className="badge" style={{ background: 'var(--jf-bg-raised)', color: 'var(--jf-text-muted)' }}>
                {group.items.length} file{group.items.length === 1 ? '' : 's'}
              </span>
              <span style={{ fontSize: '0.75rem', color: 'var(--jf-text-muted)' }}>{new Date(group.confirmed_at).toLocaleString()}</span>
              <span className="badge" style={{ background: 'var(--jf-primary-dim)', color: 'var(--jf-primary)' }}>{group.history_id.slice(0, 6)}</span>
            </div>

            {isExpanded && (
              <div style={{ marginTop: '12px' }}>
                <div style={{ overflowX: 'auto' }}>
                  <table className="admin-table" style={{ width: '100%' }}>
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Current Target</th>
                        <th>New Target (edit)</th>
                        <th>Trail</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.items.map((item) => {
                        const currentTarget = item.target_path
                        const edited = groupEdits[item.confirm_id] ?? currentTarget
                        const trail = item.pathHistory || item.path_history_json ? (() => { try { const h = item.pathHistory || JSON.parse(item.path_history_json || '[]'); return Array.isArray(h) ? h.join(' → ') : ''; } catch { return ''; } })() : `${item.source_path} → ${item.target_path}`
                        return (
                          <tr key={item.confirm_id}>
                            <td style={{ fontFamily: 'monospace', fontSize: '0.78rem', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.source_path}>
                              {item.source_path}
                            </td>
                            <td style={{ fontFamily: 'monospace', fontSize: '0.78rem', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.target_path}>
                              {item.target_path}
                            </td>
                            <td>
                              <input
                                type="text"
                                value={edited}
                                onChange={(e) => handleEditChange(group.history_id, item.confirm_id, e.target.value)}
                                style={{ width: '260px', fontFamily: 'monospace', fontSize: '0.78rem' }}
                                placeholder="New target path"
                              />
                            </td>
                            <td style={{ fontSize: '0.7rem', color: 'var(--jf-text-muted)', maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={trail}>
                              {trail}
                            </td>
                            <td>
                              <span className={`badge ${item.status === 'failed' ? 'skip' : item.status === 'undone' ? 'skip' : 'move'}`}>
                                {item.status}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <div style={{ display: 'flex', gap: '8px', marginTop: '12px', justifyContent: 'flex-end', alignItems: 'center' }}>
                  <button type="button" className="small" onClick={() => handleUndo(group)} disabled={busy === group.history_id}>
                    {busy === group.history_id ? 'Undoing…' : 'Undo'}
                  </button>
                  <button
                    type="button"
                    className="small primary"
                    onClick={() => handleRetarget(group)}
                    disabled={busy === group.history_id || !hasEdits}
                  >
                    {busy === group.history_id ? 'Moving…' : 'Save & Move Again'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
