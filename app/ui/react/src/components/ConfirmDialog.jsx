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
  return (
    <div className="modal-overlay" id="confirmDialog">
      <div className="modal modal-sm" role="dialog" aria-modal="true" aria-labelledby="confirmDialogTitle">
        <h3 id="confirmDialogTitle">{title}</h3>
        {message ? <div className="confirm-dialog-message">{message}</div> : null}
        {detail ? <pre className="confirm-dialog-detail">{detail}</pre> : null}
        <div className="modal-actions">
          <button id="confirmDialogCancel" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button id="confirmDialogConfirm" className={'primary' + (danger ? ' danger' : '')} onClick={onConfirm}>
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