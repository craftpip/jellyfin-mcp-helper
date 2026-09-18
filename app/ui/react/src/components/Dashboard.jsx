import { useState, useEffect } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { apiGet } from '../api/apiClient.js'

export default function Dashboard() {
  const { state, actions } = useAppStore()
  const { reportSummary, jellyfinLibraries, undoTick } = state
  const [history, setHistory] = useState(null)
  const [undoing, setUndoing] = useState(false)

  // Derive quick stats from last report if available, otherwise from libraries
  const totalSkipped = reportSummary?.skipped ?? 0
  const totalMovies = reportSummary?.movies ?? 0
  const totalSeries = reportSummary?.series ?? 0
  const actionsNeeded = reportSummary?.action_required ?? 0
  const hasReport = reportSummary && (actionsNeeded > 0 || totalSkipped > 0)

  useEffect(() => {
    if (hasReport) return
    let cancelled = false
    apiGet('/scans/history?limit=3').then(res => {
      if (!cancelled && res?.history?.length) setHistory(res.history)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [hasReport, undoTick])

  async function handleUndo(scanId) {
    setUndoing(true)
    try { await actions.undoScan(scanId) } finally { setUndoing(false) }
  }

  if (hasReport) {
    // Dense one-line status bar when idle
    return (
      <div className="panel dash-bar">
        <span className="dash-title">Last scan</span>
        <span className="dash-stats">
          <b>{totalMovies}</b> movies · <b>{totalSeries}</b> series · <b>{totalSkipped}</b> skipped ·{' '}
          <b className={actionsNeeded ? 'warn-t' : 'ok-t'}>{actionsNeeded}</b> {actionsNeeded ? 'to move' : 'all tidy'}
        </span>
        <span className="dash-actions">
          {jellyfinLibraries.length > 0 && (
            <span className="hint">
              {jellyfinLibraries.length} libraries
            </span>
          )}
          {(reportSummary?.moved ?? 0) > 0 && (
            <button
              className="small"
              style={{ marginLeft: jellyfinLibraries.length ? '8px' : 'auto' }}
              disabled={undoing}
              onClick={() => handleUndo('current')}
            >
              {undoing ? 'Undoing…' : 'Undo moves'}
            </button>
          )}
          <button className="small" style={{ marginLeft: '8px' }} onClick={() => actions.setPage('history')}>
            View in History
          </button>
        </span>
      </div>
    )
  }

  if (history && history.length) {
    const last = history[0]
    return (
      <div className="panel dash-bar">
        <span className="dash-title">Last scan <span className="hint">· history</span></span>
        <span className="dash-stats">
          <b>{last.movies ?? 0}</b> movies · <b>{last.series ?? 0}</b> series · <b>{last.skipped ?? 0}</b> skipped ·{' '}
          <b className={last.action_required ? 'warn-t' : 'ok-t'}>{last.action_required ?? 0}</b> {last.action_required ? 'to move' : 'all tidy'}
        </span>
        <span className="dash-actions">
          <span className="hint">{new Date(last.saved_at).toLocaleString()}</span>
          {(last.moved ?? 0) > 0 && (
            <button
              className="small"
              style={{ marginLeft: '8px' }}
              disabled={undoing}
              onClick={() => handleUndo(last.scan_id)}
            >
              {undoing ? 'Undoing…' : `Undo ${last.moved} move${last.moved === 1 ? '' : 's'}`}
            </button>
          )}
          <button className="small" style={{ marginLeft: '8px' }} onClick={() => actions.setPage('history')}>
            View in History
          </button>
        </span>
        {history.length > 1 && (
          <div style={{ marginTop: '8px', fontSize: '0.72rem', color: 'var(--jf-text-muted)' }}>
            Recent: {history.slice(1, 4).map(h => `${h.scan_id.slice(0, 6)}… ${h.action_required} to move · ${h.skipped} skipped`).join('  ·  ')}
          </div>
        )}
      </div>
    )
  }

  // Fresh install / no report yet
  if (jellyfinLibraries.length === 0) return null
  return (
    <div className="panel" style={{ background: 'var(--jf-bg-raised)', borderStyle: 'dashed' }}>
      <h2 style={{ margin: '0 0 6px 0', fontSize: '0.95rem' }}>Your libraries</h2>
      <div style={{ color: 'var(--jf-text-muted)', fontSize: '0.85rem' }}>
        {jellyfinLibraries.map(l => l.name).join(' · ')} — ready to scan.
        <span style={{ marginLeft: '8px', color: 'var(--jf-text-faint)' }}>
          {jellyfinLibraries.length} libraries connected
        </span>
      </div>
    </div>
  )
}
