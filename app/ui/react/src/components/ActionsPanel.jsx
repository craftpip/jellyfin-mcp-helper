import { useMemo } from 'react'
import { useAppStore } from '../store/AppStore.jsx'

export default function ActionsPanel() {
  const { state, actions } = useAppStore()
  const { scanId, scanRunning, confirmActive, jellyfinLibraries, libraryScanning, selectedIds, currentItems } = state

  const hasActionableSelection = useMemo(
    () =>
      selectedIds.some((id) => {
        const item = currentItems.find((i) => i.confirmId === id)
        return item && item.action !== 'skip'
      }),
    [selectedIds, currentItems]
  )

  return (
    <div className="panel">
      <h2>Actions</h2>
      <div className="btn-row">
        <button
          className="primary"
          id="btnStartScan"
          disabled={scanRunning || confirmActive}
          onClick={actions.startScan}
        >
          {scanRunning ? 'Scanning...' : 'Start Scan'}
        </button>
        <button id="btnReport" disabled={!scanId} onClick={actions.fetchReport}>
          Get Report
        </button>
        <button
          className="warn"
          id="btnConfirm"
          disabled={!hasActionableSelection || confirmActive}
          onClick={actions.confirmSelected}
        >
          {state.confirmButtonLabel}
        </button>
      </div>
      <div className="panel-sub">
        <h3>Jellyfin Library Scans</h3>
        <div className="btn-row" id="libraryScanButtons">
          {jellyfinLibraries.length === 0 && (
            <span style={{ color: '#8b949e', fontSize: '0.82rem' }}>Loading libraries...</span>
          )}
          {jellyfinLibraries.map((l) => (
            <button
              key={l.name}
              className="small"
              disabled={!!libraryScanning}
              onClick={() => actions.triggerLibraryScan(l.name)}
            >
              Scan {l.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
