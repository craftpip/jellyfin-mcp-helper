import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'

export default function LibraryScanDropdown() {
  const { state, actions } = useAppStore()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    function onDocClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function pick(name) {
    setOpen(false)
    actions.triggerLibraryScan(name)
  }

  return (
    <div className="dropdown" ref={ref}>
      <button
        type="button"
        className="small dropdown-toggle"
        disabled={!!state.libraryScanning}
        onClick={() => setOpen((o) => !o)}
      >
        {state.libraryScanning ? 'Scanning ' + state.libraryScanning + '...' : 'Scan library...'}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="dropdown-menu">
          {state.jellyfinLibraries.length === 0 ? (
            <div className="dropdown-empty">Loading libraries...</div>
          ) : (
            state.jellyfinLibraries.map((l) => (
              <button type="button" key={l.name} className="dropdown-item" onClick={() => pick(l.name)}>
                Scan {l.name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
