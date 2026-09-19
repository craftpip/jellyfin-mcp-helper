import { useState, useRef, useEffect } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import LibraryScanDropdown from './LibraryScanDropdown.jsx'
import logoUrl from '../assets/jellysort-logo.png'

export default function TopBar() {
  const { state, actions } = useAppStore()
  const [scanMenuOpen, setScanMenuOpen] = useState(false)
  const scanMenuRef = useRef(null)
  const barRef = useRef(null)
  useEffect(() => {
    const el = barRef.current
    if (!el) return
    const onScroll = () => { el.classList.toggle('stuck', window.scrollY > 8) }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
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
      <div className="top-bar" ref={barRef}>
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
              <span className="scan-split">
              <button
                type="button"
                className="primary"
                id="btnScanHeader"
                disabled={state.confirmActive}
                onClick={() => { setScanMenuOpen(false); actions.startScan({ fullRescan: false }) }}
                title="Scan for new files only (preserves edits)"
              >
                Scan
              </button>
              <button
                type="button"
                className="primary"
                disabled={state.confirmActive}
                onClick={() => setScanMenuOpen((v) => !v)}
                title="More scan options"
                style={{ padding: '0 10px' }}
                aria-label="More scan options"
              >
                ▾
              </button>
              </span>
              {scanMenuOpen && (
                <div className="scan-menu">
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
          {state.page !== 'scan' && (
            <button
              type="button"
              className="small"
              onClick={() => actions.setPage('scan')}
              title="Back to Scan & Move report"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ display: 'block' }}>
                <path d="M19 12H5" />
                <path d="M12 19l-7-7 7-7" />
              </svg>
              Report
            </button>
          )}
          {state.jellyfinLibraries.length > 0 && <LibraryScanDropdown />}
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
          {state.authRequired && state.authed && (
            <button type="button" className="small logout-btn" onClick={actions.logout} title="Log out of this panel">
              Logout
            </button>
          )}
        </div>
      </div>
    </>
  )
}
