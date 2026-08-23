import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api/apiClient.js'
import { useAppStore } from '../store/AppStore.jsx'
import { groupItems, mapReportItems, matchesFilter } from '../utils/report.js'
import { formatBytes } from '../utils/format.js'
import PathPills from './PathPills.jsx'

function highlight(text, query) {
  if (!query || !text) return text
  const q = query.trim()
  if (!q) return text
  const lower = text.toLowerCase()
  const idx = lower.indexOf(q.toLowerCase())
  if (idx === -1) return text
  const before = text.slice(0, idx)
  const match = text.slice(idx, idx + q.length)
  const after = text.slice(idx + q.length)
  return (
    <>
      {before}
      <mark style={{ background: 'rgba(0,164,220,0.25)', color: 'inherit', padding: '0 1px', borderRadius: '2px' }}>{match}</mark>
      {after}
    </>
  )
}

export default function HistoryPage() {
  const { actions } = useAppStore()
  const [groups, setGroups] = useState([])
  const [scans, setScans] = useState([])
  const [scanReports, setScanReports] = useState({}) // scan_id -> report
  const [scanExpanded, setScanExpanded] = useState({})
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState({})
  const [editing, setEditing] = useState({}) // history_id -> {confirmId -> newTarget}
  const [busy, setBusy] = useState(null)

  async function load() {
    setLoading(true)
    try {
      const [res, scanRes] = await Promise.all([
        apiGet('/history?limit=50').catch(() => ({ groups: [] })),
        apiGet('/scans/history?limit=20').catch(() => ({ history: [] })),
      ])
      setGroups(res.groups || [])
      const history = scanRes.history || []
      setScans(history)
      // Eagerly fetch first 3 scans, lazy-load the rest on expand
      const reports = {}
      await Promise.all(
        history.slice(0, 3).map(async (s) => {
          try {
            const r = await apiGet(`/scans/history/${s.scan_id}`)
            reports[s.scan_id] = r
          } catch {}
        })
      )
      setScanReports(reports)
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

  async function toggleScan(scanId) {
    const willExpand = !scanExpanded[scanId]
    setScanExpanded((prev) => ({ ...prev, [scanId]: willExpand }))
    if (willExpand && !scanReports[scanId]) {
      try {
        const r = await apiGet(`/scans/history/${scanId}`)
        setScanReports((prev) => ({ ...prev, [scanId]: r }))
      } catch (e) {
        actions.toast('Failed to load scan report: ' + e.message, 'err')
      }
    }
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

  return (
    <div className="admin-page" style={{ maxWidth: 'none' }}>
      <div className="admin-header">
        <h2>History</h2>
        <div className="hint">Every confirmed group is saved here. You can review, undo, or rename folders and move again. The full path trail is kept for display. Your past scans are below, shown exactly like the Scan report so you can move files again.</div>
      </div>

      {scans.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 8px 0' }}>Scans history ({scans.length}) — shown exactly like Scan report, with Move again</h3>
          {scans.map((s) => (
            <ScanHistoryCard
              key={s.scan_id}
              scan={s}
              report={scanReports[s.scan_id]}
              expanded={!!scanExpanded[s.scan_id]}
              onToggle={() => toggleScan(s.scan_id)}
            />
          ))}
        </div>
      )}

      {groups.length > 0 && <h3 style={{ margin: '16px 0 8px 0' }}>Confirmed groups ({groups.length})</h3>}
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

function ScanHistoryCard({ scan, report, expanded, onToggle }) {
  const { actions } = useAppStore()
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmExpanded, setConfirmExpanded] = useState({})

  if (!report || !report.items) {
    return (
      <div className="panel" style={{ padding: '12px', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer' }} onClick={onToggle}>
          <span style={{ fontSize: '0.8rem', color: 'var(--jf-text-muted)' }}>{expanded ? '▼' : '▶'}</span>
          <strong style={{ flex: 1 }}>{scan.scan_id.slice(0, 8)} — {new Date(scan.saved_at).toLocaleString()}</strong>
          <span className="badge">{scan.movies ?? 0} Movies</span>
          <span className="badge">{scan.series ?? 0} Series</span>
          <span className="badge" style={{ background: 'var(--jf-primary-dim)', color: 'var(--jf-primary)' }}>{scan.action_required} to move</span>
        </div>
        {expanded && <div style={{ padding: 12, color: 'var(--jf-text-muted)' }}>Loading report…</div>}
      </div>
    )
  }

  const allItems = mapReportItems(report)
  const groups = groupItems(allItems)
  const summary = report.summary || {}

  async function handleConfirmGroup(gi) {
    const group = groups[gi]
    if (!group) return
    const itemIds = group.items.filter((i) => i.action !== 'skip').map((i) => i.confirmId)
    if (!itemIds.length) {
      actions.toast('No move/replace items in this group', 'info')
      return
    }
    if (!window.confirm(`Move ${itemIds.length} file(s) from "${group.title}" again?`)) return
    setBusy(true)
    try {
      const res = await apiPost(`/scans/${scan.scan_id}/confirm`, { itemIds })
      actions.toast(`Queued ${itemIds.length} file(s) — ${res.queue_length ? 'queued' : 'started'}`, 'good')
    } catch (e) {
      actions.toast('Move again failed: ' + e.message, 'err')
    } finally {
      setBusy(false)
    }
  }

  const FILTER_DEFS = [
    ['all', 'All'],
    ['move', 'New'],
    ['replace', 'Replace'],
    ['extra', 'Extras'],
  ]
  const counts = {
    all: allItems.filter((i) => i.action !== 'skip').length,
    move: allItems.filter((i) => i.action === 'move').length,
    replace: allItems.filter((i) => i.action === 'replace').length,
    extra: allItems.filter((i) => i.itemType === 'extra').length,
  }

  return (
    <div className="panel" style={{ padding: '12px', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer' }} onClick={onToggle}>
        <span style={{ fontSize: '0.8rem', color: 'var(--jf-text-muted)' }}>{expanded ? '▼' : '▶'}</span>
        <strong style={{ flex: 1 }}>{scan.scan_id.slice(0, 8)} — {new Date(scan.saved_at).toLocaleString()}</strong>
        <span className="badge">{summary.movies ?? scan.movies ?? 0} Movies</span>
        <span className="badge">{summary.series ?? scan.series ?? 0} Series</span>
        <span className="badge" style={{ background: 'var(--jf-primary-dim)', color: 'var(--jf-primary)' }}>{summary.action_required ?? scan.action_required ?? 0} to move</span>
      </div>

      {expanded && (
        <div style={{ marginTop: 12 }}>
          <div className="summary-strip" style={{ margin: '0 0 12px 0' }}>
            <div className="summary-pill"><strong>{summary.movies ?? 0}</strong> Movies</div>
            <div className="summary-pill"><strong>{summary.series ?? 0}</strong> Series</div>
            <div className="summary-pill" style={{ color: '#9aa4ab' }}><strong>{summary.skipped ?? 0}</strong> Skipped</div>
            <div className="summary-pill" style={{ color: '#e8b34b' }}><strong>{summary.action_required ?? 0}</strong> to move</div>
            <div className="search-bar" style={{ marginLeft: 8, maxWidth: 260, flex: '0 1 240px', minWidth: 180, marginBottom: 0 }}>
              <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by title, path..." style={{ borderRadius: 999 }} />
              {query && <button className="small" onClick={() => setQuery('')} style={{ borderRadius: 999 }}>Clear</button>}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
            <div className="filter-chips" style={{ margin: 0, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              {FILTER_DEFS.map(([k, label]) => (
                <button key={k} className={'filter-chip' + (filter === k ? ' active' : '')} onClick={() => setFilter(k)}>
                  {filter === k ? '✓ ' : ''}{label} <span className="chip-count">{counts[k]}</span>
                </button>
              ))}
            </div>
          </div>

          {groups.map((group, gi) => {
            const gid = `scan-${scan.scan_id}-group-${gi}`
            const isExpanded = confirmExpanded[gid] ?? true
            const visibleItems = group.items.filter((item) => {
              const q = query.trim()
              const text = [item.title, item.episode, item.sourceName, item.sourcePath, item.targetPath].filter(Boolean).join(' ').toLowerCase()
              let match = true
              if (q && !text.includes(q.toLowerCase())) match = false
              if (filter === 'move' && item.action !== 'move') match = false
              if (filter === 'replace' && item.action !== 'replace') match = false
              if (filter === 'extra' && item.itemType !== 'extra') match = false
              return match
            })
            if (visibleItems.length === 0) return null
            const isSeries = group.items[0].itemType === 'series'
            return (
              <div key={gid} style={{ marginBottom: 12 }}>
                <div className={'group-header' + (isExpanded ? ' expanded' : ' collapsed')} onClick={() => setConfirmExpanded((p) => ({ ...p, [gid]: !p[gid] }))} style={{ cursor: 'pointer' }}>
                  <span className={'arrow' + (isExpanded ? '' : ' collapsed')}>▾</span>
                  <span className="g-title">{group.title}</span>
                  <span className="g-count">{group.items.length} item(s)</span>
                  {group.totalSize > 0 && <span className="g-size">{formatBytes(group.totalSize)}</span>}
                </div>
                <div className={'group-body' + (isExpanded ? '' : ' collapsed')}>
                  <div className="group-toolbar">
                    <span className="chk-text">{group.title}</span>
                    <button className="warn small" style={{ marginLeft: 'auto' }} onClick={() => handleConfirmGroup(gi)} disabled={busy}>
                      {busy ? 'Queuing…' : 'Move again'}
                    </button>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        <th style={{ width: '150px' }}>Action</th>
                        {isSeries && <th style={{ width: '90px' }}>Episode</th>}
                        <th colSpan={2}>Source → Target Path</th>
                        <th style={{ width: '90px', textAlign: 'right' }}>Size</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleItems.map((item) => (
                        <tr key={item.confirmId} data-title={item.title.toLowerCase()} data-action={item.action} data-fileexists={item.fileExists ? 'true' : 'false'}>
                          <td>
                            <div className="action-cell">
                              <span className={'badge action-' + item.action}>{item.action === 'replace' ? 'Existing' : 'New'}</span>
                              <span className="path-status"><PathPills item={item} /></span>
                            </div>
                          </td>
                          {isSeries && <td>{item.episode || ''}</td>}
                          <td colSpan={2}>
                            <div className="path-cell">
                              <div className="source-name" title={item.sourcePath}>{item.sourcePath.split('/').pop()}</div>
                              <div style={{ fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--jf-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.targetPath}>{item.targetPath}</div>
                            </div>
                          </td>
                          <td style={{ whiteSpace: 'nowrap', textAlign: 'right', color: '#9aa4ab', fontSize: '0.8rem' }}>{item.fileSize ? formatBytes(item.fileSize) : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
