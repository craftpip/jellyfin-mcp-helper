import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/apiClient.js'
import { useAppStore } from '../store/AppStore.jsx'
import { formatBytes } from '../utils/format.js'
import PathPills from './PathPills.jsx'
import { FolderPicker } from './BrowseModal.jsx'

export default function HistoryPage() {
  const { actions } = useAppStore()
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState({})
  const [editing, setEditing] = useState({}) // history_id -> {confirmId -> newTarget}
  const [busy, setBusy] = useState(null)
  const [browseRow, setBrowseRow] = useState(null) // {historyId, confirmId, title}
  const [trailPopup, setTrailPopup] = useState(null) // {pathHistory, title}

  async function load() {
    setLoading(true)
    try {
      const res = await apiGet('/history?limit=50')
      setGroups(res.groups || [])
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

  async function handleDeleteSource(group, item) {
    if (!window.confirm(`Delete leftover source file?\n${item.source_path}`)) return
    setBusy(group.history_id)
    try {
      const res = await apiPost(`/history/${group.history_id}/delete-source`, { confirmId: item.confirm_id })
      if (res.deleted) {
        actions.toast('Deleted leftover source file', 'good')
      } else {
        actions.toast('Source file no longer exists', 'warn')
      }
      await load()
    } catch (e) {
      actions.toast('Delete failed: ' + e.message, 'err')
    } finally {
      setBusy(null)
    }
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

  if (!groups.length) {
    return (
      <div className="panel">
        <h2>History</h2>
        <div className="hint">No confirms yet — scan and confirm a group to see it here.</div>
      </div>
    )
  }

  return (
    <div className="admin-page" style={{ maxWidth: 'none' }}>
      <div className="admin-header">
        <h2>History</h2>
        <div className="hint">Every confirmed group is saved here. You can review, undo, or rename folders and move again. Full movement trail is kept for every file.</div>
      </div>

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
                  <table className="admin-table" style={{ width: '100%', tableLayout: 'fixed' }}>
                    <thead>
                      <tr>
                        <th style={{ width: '150px' }}>Action</th>
                        <th style={{ minWidth: 0 }}>Source → Target Path</th>
                        <th style={{ width: '90px', textAlign: 'right' }}>Size</th>
                        <th style={{ width: '140px', textAlign: 'left' }}>Trail</th>
                        <th style={{ width: '90px' }}>Status</th>
                        <th style={{ width: '70px', textAlign: 'right' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.items.map((item) => {
                        const currentTarget = item.target_path
                        const edited = groupEdits[item.confirm_id] ?? currentTarget
                        const history = item.pathHistory && item.pathHistory.length ? item.pathHistory : [item.source_path, item.target_path].filter(Boolean)
                        const hops = Math.max(0, history.length - 1)
                        const trailSummary = hops === 0 ? '—' : hops === 1 ? '1 hop' : `${hops} hops`
                        const trail = history.join(' → ')
                        return (
                          <tr key={item.confirm_id}>
                            <td>
                              <div className="action-cell">
                                {item.cross_drive ? (
                                  <span className="crossdrive-badge" title="Moved between hard drives">
                                    Cross-drive
                                  </span>
                                ) : null}
                                {item.suspect ? (
                                  <span className="suspect-badge" title={item.correction_note || 'Suspect classification — double-check the target'}>
                                    Suspect
                                  </span>
                                ) : null}
                                {item.corrected ? (
                                  <span className="corrected-badge" title={item.correction_note || 'Reclassified after review'}>
                                    Corrected
                                  </span>
                                ) : null}
                                <span className="path-status">
                                  <PathPills item={{ itemType: item.item_type, pathExists: item.pathExists }} />
                                </span>
                              </div>
                            </td>
                            <td>
                              <div className="path-cell">
                                <div className="source-name" title={item.source_path}>
                                  {item.source_path}
                                </div>
                                <input
                                  type="text"
                                  className="target-input"
                                  value={edited}
                                  onChange={(e) => handleEditChange(group.history_id, item.confirm_id, e.target.value)}
                                  placeholder="New target path"
                                />
                                <div className="target-tools">
                                  <button
                                    type="button"
                                    className="small browse-btn"
                                    onClick={() =>
                                      setBrowseRow({ historyId: group.history_id, confirmId: item.confirm_id, title: item.source_path })
                                    }
                                  >
                                    Browse…
                                  </button>
                                </div>
                              </div>
                            </td>
                            <td style={{ whiteSpace: 'nowrap', textAlign: 'right', color: '#9aa4ab', fontSize: '0.8rem' }}>
                              {item.file_size ? formatBytes(item.file_size) : ''}
                            </td>
                            <td style={{ textAlign: 'left' }}>
                              <button
                                type="button"
                                className="small"
                                style={{ fontSize: '0.7rem', padding: '2px 6px', whiteSpace: 'nowrap', textAlign: 'left' }}
                                title={trail}
                                onClick={() => setTrailPopup({ pathHistory: history, title: item.source_path, item })}
                              >
                                {trailSummary} <span style={{ color: 'var(--jf-text-muted)', fontWeight: 400 }}>• {history.length} paths</span>
                              </button>
                            </td>
                            <td>
                              <span className={`badge ${item.status === 'failed' ? 'skip' : item.status === 'undone' ? 'skip' : 'move'}`}>
                                {item.status}
                              </span>
                            </td>
                            <td style={{ textAlign: 'right' }}>
                              {item.source_exists ? (
                                <button
                                  type="button"
                                  className="danger small"
                                  disabled={busy === group.history_id}
                                  onClick={() => handleDeleteSource(group, item)}
                                  title="Delete the leftover source file"
                                >
                                  Delete
                                </button>
                              ) : null}
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

      {browseRow && (
        <FolderPicker
          title={browseRow.title}
          onPick={(directory) => handleEditChange(browseRow.historyId, browseRow.confirmId, directory)}
          onClose={() => setBrowseRow(null)}
        />
      )}

      {trailPopup && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 60,
            padding: '20px',
          }}
          onClick={() => setTrailPopup(null)}
        >
          <div
            style={{
              background: 'var(--jf-bg-raised, #242629)',
              border: '1px solid var(--jf-border, #2E3229)',
              borderRadius: '12px',
              maxWidth: '920px',
              width: '92%',
              maxHeight: '82vh',
              overflow: 'auto',
              padding: '18px',
              boxShadow: '0 12px 28px rgba(0,0,0,0.28)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '14px' }}>
              <strong style={{ fontSize: '0.95rem', letterSpacing: '0.01em' }}>Full movement trail</strong>
              <button type="button" className="small" onClick={() => setTrailPopup(null)}>
                Close
              </button>
            </div>
            {trailPopup.title && (
              <div style={{ fontSize: '0.75rem', color: 'var(--jf-text-muted)', marginBottom: '12px', wordBreak: 'break-all' }}>{trailPopup.title}</div>
            )}
            <div style={{ overflowX: 'auto', border: '1px solid var(--jf-border, #2E3229)', borderRadius: '8px' }}>
              <table className="admin-table" style={{ width: '100%', margin: 0 }}>
                <thead>
                  <tr>
                    <th style={{ width: '44px', textAlign: 'left', fontSize: '0.7rem', color: 'var(--jf-text-muted)', fontWeight: 500, padding: '8px 10px', borderBottom: '1px solid var(--jf-border, #2E3229)' }}>#</th>
                    <th style={{ textAlign: 'left', fontSize: '0.7rem', color: 'var(--jf-text-muted)', fontWeight: 500, padding: '8px 10px', borderBottom: '1px solid var(--jf-border, #2E3229)' }}>Path</th>
                    <th style={{ width: '130px', textAlign: 'left', fontSize: '0.7rem', color: 'var(--jf-text-muted)', fontWeight: 500, padding: '8px 10px', borderBottom: '1px solid var(--jf-border, #2E3229)' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {trailPopup.pathHistory.map((p, idx) => {
                    const isFirst = idx === 0
                    const isLast = idx === trailPopup.pathHistory.length - 1
                    const hopAction = isFirst ? 'source' : idx === 1 ? (trailPopup.item?.action === 'replace' ? 'replaced' : 'new') : 'new (retarget)'
                    const badgeBg = hopAction === 'source' ? 'rgba(154,164,171,0.14)' : hopAction.includes('replaced') ? 'rgba(224,90,51,0.14)' : 'rgba(62,207,142,0.14)'
                    const badgeColor = hopAction === 'source' ? 'var(--jf-text-muted)' : hopAction.includes('replaced') ? '#E05A33' : '#3ecf8e'
                    return (
                      <tr key={idx} style={{ background: isLast ? 'rgba(0,164,220,0.04)' : 'transparent' }}>
                        <td style={{ padding: '9px 10px', fontSize: '0.75rem', color: 'var(--jf-text-muted)', textAlign: 'left', borderTop: idx ? '1px solid rgba(46,50,41,0.6)' : 'none' }}>{idx + 1}</td>
                        <td style={{ padding: '9px 10px', fontSize: '0.8rem', wordBreak: 'break-all', color: isLast ? 'var(--jf-text-primary, #F5F0E6)' : 'var(--jf-text-muted)', textAlign: 'left', borderTop: idx ? '1px solid rgba(46,50,41,0.6)' : 'none' }}>{p}</td>
                        <td style={{ padding: '9px 10px', textAlign: 'left', borderTop: idx ? '1px solid rgba(46,50,41,0.6)' : 'none' }}>
                          <span style={{ fontSize: '0.65rem', padding: '2px 7px', borderRadius: '999px', background: badgeBg, color: badgeColor, whiteSpace: 'nowrap' }}>{hopAction}</span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ fontSize: '0.7rem', color: 'var(--jf-text-muted)', marginTop: '12px', textAlign: 'left' }}>{trailPopup.pathHistory.length} paths • {Math.max(0, trailPopup.pathHistory.length - 1)} moves chained {trailPopup.item?.action ? `• first was ${trailPopup.item.action === 'replace' ? 'replaced' : 'new file'}` : ''}</div>
          </div>
        </div>
      )}
    </div>
  )
}
