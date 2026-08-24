import { useEffect, useState, useMemo } from 'react'
import { useAppStore } from '../store/AppStore.jsx'

export default function CommandPalette({ open, onClose }) {
  const { state, actions } = useAppStore()
  const [query, setQuery] = useState('')

  const commands = useMemo(() => {
    const base = [
      { id: 'scan', label: 'Start Scan', hint: 'Scan downloads for new files', action: () => { onClose(); actions.startScan() }, show: state.page === 'scan' && !state.scanRunning },
      { id: 'report', label: 'Go to Scan & Move', hint: 'Back to scan report', action: () => { onClose(); actions.setPage('scan') } },
      { id: 'settings', label: 'Open Settings', hint: 'Configure JellySort', action: () => { onClose(); actions.setPage('settings') } },
      { id: 'logs', label: state.logsVisible ? 'Hide Logs' : 'Show Logs', hint: 'Toggle log panel', action: () => { onClose(); actions.toggleLogs() } },
      { id: 'copy-scan-id', label: 'Copy scan ID', hint: state.scanId || 'No scan', action: () => { if (state.scanId) { onClose(); actions.copyText(state.scanId) } }, show: !!state.scanId },
    ]
    return base.filter(c => c.show !== false)
  }, [state.page, state.scanRunning, state.logsVisible, state.scanId])

  const filtered = useMemo(() => {
    if (!query) return commands
    const q = query.toLowerCase()
    return commands.filter(c => c.label.toLowerCase().includes(q) || c.hint.toLowerCase().includes(q))
  }, [commands, query])

  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  useEffect(() => {
    if (!open) return
    const el = document.getElementById('cmd-palette-input')
    if (el) setTimeout(() => el.focus(), 30)
  }, [open])

  if (!open) return null

  return (
    <div className="modal-overlay" onClick={onClose} style={{ zIndex: 400 }}>
      <div className="modal" style={{ maxWidth: '480px', padding: 0, overflow: 'hidden' }} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Command palette">
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--jf-border)' }}>
          <input
            id="cmd-palette-input"
            type="text"
            placeholder="Type a command… (e.g. scan, settings)"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Escape') onClose()
              if (e.key === 'Enter' && filtered[0]) filtered[0].action()
            }}
            style={{ width: '100%', fontSize: '0.95rem' }}
          />
        </div>
        <div style={{ maxHeight: '260px', overflowY: 'auto' }}>
          {filtered.length === 0 && <div style={{ padding: '14px', color: 'var(--jf-text-muted)', fontSize: '0.85rem' }}>No commands match “{query}”</div>}
          {filtered.map(c => (
            <button
              key={c.id}
              onClick={c.action}
              style={{
                width: '100%', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                background: 'none', border: 'none', borderBottom: '1px solid var(--jf-border-soft)',
                padding: '10px 14px', color: 'var(--jf-text)', cursor: 'pointer', fontSize: '0.85rem'
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--jf-surface-hover)'}
              onMouseLeave={e => e.currentTarget.style.background = 'none'}
            >
              <span>{c.label}</span>
              <span style={{ color: 'var(--jf-text-muted)', fontSize: '0.75rem' }}>{c.hint}</span>
            </button>
          ))}
        </div>
        <div style={{ padding: '8px 14px', color: 'var(--jf-text-faint)', fontSize: '0.7rem', textAlign: 'center', borderTop: '1px solid var(--jf-border-soft)' }}>
          Press <kbd>⌘K</kbd> or <kbd>Ctrl+K</kbd> to open · <kbd>Esc</kbd> to close
        </div>
      </div>
    </div>
  )
}
