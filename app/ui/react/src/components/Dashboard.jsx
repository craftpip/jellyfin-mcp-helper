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
    // Show last report stats as dashboard when idle
    return (
      <div className="panel" style={{ background: 'linear-gradient(135deg, rgba(0,164,220,0.08), rgba(62,207,142,0.06))' }}>
        <h2 style={{ margin: '0 0 8px 0', fontSize: '0.95rem' }}>Last scan</h2>
        <div className="summary-strip" style={{ margin: '0' }}>
          <div className="summary-pill"><strong>{totalMovies}</strong> Movies</div>
          <div className="summary-pill"><strong>{totalSeries}</strong> Series</div>
          <div className="summary-pill" style={{ color: '#9aa4ab' }}><strong>{totalSkipped}</strong> Skipped</div>
          <div className="summary-pill" style={{ color: actionsNeeded ? '#e8b34b' : '#3ecf8e' }}>
            <strong>{actionsNeeded}</strong> {actionsNeeded ? 'to move' : 'all tidy'}
          </div>
          {jellyfinLibraries.length > 0 && (
            <div className="summary-pill" style={{ marginLeft: 'auto' }}>
              {jellyfinLibraries.length} libraries
            </div>
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
        </div>
      </div>
    )
  }

  if (history && history.length) {
    const last = history[0]
    return (
      <div className="panel" style={{ background: 'linear-gradient(135deg, rgba(0,164,220,0.08), rgba(62,207,142,0.06))' }}>
        <h2 style={{ margin: '0 0 8px 0', fontSize: '0.95rem' }}>Last scan (from history) — still on disk after restart</h2>
        <div className="summary-strip" style={{ margin: '0' }}>
          <div className="summary-pill"><strong>{last.movies ?? 0}</strong> Movies</div>
          <div className="summary-pill"><strong>{last.series ?? 0}</strong> Series</div>
          <div className="summary-pill" style={{ color: '#9aa4ab' }}><strong>{last.skipped ?? 0}</strong> Skipped</div>
          <div className="summary-pill" style={{ color: last.action_required ? '#e8b34b' : '#3ecf8e' }}>
            <strong>{last.action_required ?? 0}</strong> {last.action_required ? 'to move' : 'all tidy'}
          </div>
          <div style={{ marginLeft: 'auto', fontSize: '0.7rem', color: 'var(--jf-text-muted)' }}>
            {new Date(last.saved_at).toLocaleString()}
          </div>
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
        </div>
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
