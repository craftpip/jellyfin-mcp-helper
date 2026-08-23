import { useAppStore } from '../store/AppStore.jsx'
import LibraryScanDropdown from './LibraryScanDropdown.jsx'
import logoUrl from '../assets/jellysort-logo.png'

export default function TopBar() {
  const { state, actions } = useAppStore()
  return (
    <>
      <div className="top-bar">
        <div className="brand">
          <img className="brand-logo" src={logoUrl} alt="JellySort logo" />
          <div>
            <h1>JellySort</h1>
            <div className="subtitle">Move your new files to the dedicated library folders where they belong</div>
          </div>
        </div>
        <div className="top-actions">
          {state.page !== 'scan' && (
            <button
              type="button"
              className="small"
              onClick={() => actions.setPage('scan')}
              title="Back to scan and move"
            >
              ← Scan &amp; Move
            </button>
          )}
          {state.page === 'scan' && state.reportVisible && !state.scanRunning && (
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
          {state.page === 'scan' && state.jellyfinLibraries.length > 0 && <LibraryScanDropdown />}
          <button
            type="button"
            className={`small ${state.page === 'history' ? 'active' : ''}`}
            onClick={() => actions.setPage('history')}
            title="View confirm history"
          >
            History
          </button>
          <button
            type="button"
            className={`small ${state.page === 'settings' ? 'active' : ''}`}
            onClick={() => actions.setPage('settings')}
            title="Open settings"
          >
            Settings
          </button>
          <button
            type="button"
            className={`small ${state.page === 'apikeys' ? 'active' : ''}`}
            onClick={() => actions.setPage('apikeys')}
            title="Manage API keys"
          >
            API Keys
          </button>
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
    </>
  )
}
