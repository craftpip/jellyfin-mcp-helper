import { useAppStore } from '../store/AppStore.jsx'
import LibraryScanDropdown from './LibraryScanDropdown.jsx'

export default function TopBar() {
  const { state, actions } = useAppStore()
  return (
    <div className="top-bar">
      <div>
        <h1>JellySort</h1>
        <div className="subtitle">Move your new files to the dedicated library folders where they belong</div>
      </div>
      <div className="top-actions">
        {state.reportVisible && !state.scanRunning && (
          <button
            type="button"
            className="primary"
            id="btnScanHeader"
            disabled={state.confirmActive}
            onClick={actions.startScan}
            title="Start a new scan"
          >
            Scan
          </button>
        )}
        {state.jellyfinLibraries.length > 0 && <LibraryScanDropdown />}
        <button type="button" className="small" onClick={actions.toggleLogs} title="Show or hide the log panel">
          {state.logsVisible ? 'Hide Logs' : 'Show Logs'}
        </button>
        {state.authRequired && state.authed && (
          <button type="button" className="small logout-btn" onClick={actions.logout} title="Log out of this panel">
            Log out
          </button>
        )}
      </div>
    </div>
  )
}
