import { useEffect, useRef } from 'react'
import { createRoot } from 'react-dom/client'

export function ConfirmDialog({
  title,
  message,
  detail,
  confirmLabel = 'OK',
  cancelLabel = 'Cancel',
  danger = false,
  onConfirm,
  onCancel,
}) {
  const confirmRef = useRef(null)
  const onConfirmRef = useRef(onConfirm)
  const onCancelRef = useRef(onCancel)
  onConfirmRef.current = onConfirm
  onCancelRef.current = onCancel

  useEffect(() => {
    confirmRef.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCancelRef.current?.()
      } else if (e.key === 'Enter') {
        // Let a focused Cancel button activate natively to avoid double-handling.
        if (document.activeElement?.id === 'confirmDialogCancel') return
        const tag = e.target?.tagName
        if (tag === 'TEXTAREA' || tag === 'SELECT') return
        e.preventDefault()
        onConfirmRef.current?.()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="modal-overlay" id="confirmDialog" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel?.() }}>
      <div className="modal modal-sm" role="dialog" aria-modal="true" aria-labelledby="confirmDialogTitle">
        <h3 id="confirmDialogTitle">{title}</h3>
        {message ? <div className="confirm-dialog-message">{message}</div> : null}
        {detail ? <pre className="confirm-dialog-detail">{detail}</pre> : null}
        <div className="modal-actions">
          <button id="confirmDialogCancel" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            id="confirmDialogConfirm"
            ref={confirmRef}
            className={'primary' + (danger ? ' danger' : '')}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

let host = null
let root = null

function close() {
  if (root) {
    root.unmount()
    root = null
  }
  if (host && host.parentNode) host.parentNode.removeChild(host)
  host = null
}

export function confirmDialog(opts = {}) {
  return new Promise((resolve) => {
    close()
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    const finish = (val) => {
      close()
      resolve(val)
    }
    root.render(<ConfirmDialog {...opts} onConfirm={() => finish(true)} onCancel={() => finish(false)} />)
  })
}

export default confirmDialog