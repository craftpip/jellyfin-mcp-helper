import { useState, useRef, useEffect } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import LibraryScanDropdown from './LibraryScanDropdown.jsx'
import logoUrl from '../assets/jellysort-logo.png'

export default function TopBar() {
  const { state, actions } = useAppStore()
  const [scanMenuOpen, setScanMenuOpen] = useState(false)
  const scanMenuRef = useRef(null)
  useEffect(() => {
    if (!scanMenuOpen) return
    const onDocClick = (e) => {
      if (scanMenuRef.current && !scanMenuRef.current.contains(e.target)) setScanMenuOpen(false)
    }
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [scanMenuOpen])
  return (
    <>
      <div className="top-bar">
        <div
          className="brand"
          onClick={() => actions.setPage('scan')}
          role="button"
          tabIndex={0}
          title="Go to homepage"
          style={{ cursor: 'pointer' }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              actions.setPage('scan')
            }
          }}
        >
          <img className="brand-logo" src={logoUrl} alt="JellySort logo" />
          <div>
            <h1>JellySort</h1>
            <div className="subtitle">Move your new files to the dedicated library folders where they belong</div>
          </div>
        </div>
        <div className="top-actions">
          {state.page === 'scan' && !state.scanRunning && (
            <div ref={scanMenuRef} style={{ position: 'relative', display: 'inline-flex' }}>
              <button
                type="button"
                className="primary"
                id="btnScanHeader"
                disabled={state.confirmActive}
                onClick={() => { setScanMenuOpen(false); actions.startScan({ fullRescan: false }) }}
                title="Scan for new files only (preserves edits)"
                style={{ borderTopRightRadius: 0, borderBottomRightRadius: 0 }}
              >
                Scan
              </button>
              <button
                type="button"
                className="primary"
                disabled={state.confirmActive}
                onClick={() => setScanMenuOpen((v) => !v)}
                title="More scan options"
                style={{ padding: '0 8px', borderLeft: '1px solid rgba(255,255,255,0.2)', borderTopLeftRadius: 0, borderBottomLeftRadius: 0 }}
              >
                ▾
              </button>
              {scanMenuOpen && (
                <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 4, background: 'var(--jf-bg-raised)', border: '1px solid var(--jf-border)', borderRadius: 6, boxShadow: '0 4px 12px rgba(0,0,0,0.15)', zIndex: 50, minWidth: 220, maxWidth: 'min(300px, 90vw)' }}>
                  <button
                    type="button"
                    className="small"
                    style={{ display: 'block', width: '100%', textAlign: 'left', border: 'none', background: 'transparent', padding: '8px 12px', height: 'auto', whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.3 }}
                    onClick={() => { setScanMenuOpen(false); actions.startScan({ fullRescan: false }) }}
                  >
                    Scan new only
                    <span style={{ display: 'block', fontSize: '0.72rem', color: 'var(--jf-text-muted)', whiteSpace: 'normal', wordBreak: 'break-word' }}>Add new files, keep edits</span>
                  </button>
                  <button
                    type="button"
                    className="small"
                    style={{ display: 'block', width: '100%', textAlign: 'left', border: 'none', background: 'transparent', padding: '8px 12px', borderTop: '1px solid var(--jf-border)', height: 'auto', whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.3 }}
                    onClick={() => { setScanMenuOpen(false); actions.startScan({ fullRescan: true }) }}
                  >
                    Rescan all (overwrite)
                    <span style={{ display: 'block', fontSize: '0.72rem', color: 'var(--jf-text-muted)', whiteSpace: 'normal', wordBreak: 'break-word' }}>Rebuild report, discard edits</span>
                  </button>
                </div>
              )}
            </div>
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
