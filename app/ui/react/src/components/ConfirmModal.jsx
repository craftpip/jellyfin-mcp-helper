import { useEffect, useRef } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { fileName, formatBytes, splitDrive } from '../utils/format.js'
import { isCrossDriveItem } from '../utils/report.js'

export default function ConfirmModal() {
  const { state } = useAppStore()
  const { confirmModal } = state
  if (!confirmModal.open) return null

  return <PreflightView itemIds={confirmModal.itemIds} label={confirmModal.label} />
}

function PreflightView({ itemIds, label }) {
  const { state, actions } = useAppStore()
  const items = itemIds
    .map((id) => state.currentItems.find((i) => i.confirmId === id))
    .filter(Boolean)

  const startRef = useRef(null)
  const closeRef = useRef(actions.closeConfirmModal)
  const runRef = useRef(actions.runConfirm)
  closeRef.current = actions.closeConfirmModal
  runRef.current = actions.runConfirm
  const postingRef = useRef(state.confirmPosting)
  postingRef.current = state.confirmPosting
  const idsRef = useRef(itemIds)
  idsRef.current = itemIds

  useEffect(() => {
    startRef.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeRef.current?.()
      } else if (e.key === 'Enter') {
        // Let a focused Cancel button activate natively to avoid double-handling.
        if (document.activeElement?.id === 'confirmModalCancel') return
        const tag = e.target?.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
        if (postingRef.current) return
        e.preventDefault()
        runRef.current?.(idsRef.current)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const totalSize = items.reduce((s, i) => s + (Number(i.fileSize) || 0), 0)
  const moveCount = items.filter((i) => i.action === 'move').length
  const replaceCount = items.filter((i) => i.action === 'replace').length
  const crossCount = items.filter((i) => isCrossDriveItem(i)).length

  return (
    <div className="modal-overlay" id="confirmModal">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirmModalTitle">
        <h3 id="confirmModalTitle">Confirm Move — {label || items.length + ' item(s)'}</h3>
        {state.confirmActive && (
          <div className="warn-box" id="confirmQueueWarn">
            <strong>A move is already running</strong>
            <div id="confirmQueueWarnText">
              This batch will be added to the queue and start automatically when the current move
              finishes.
            </div>
          </div>
        )}
        <div className="summary-strip">
          {[
            ['Items', items.length],
            ['Move', moveCount],
            ['Replace', replaceCount],
            crossCount > 0 && ['Cross-drive', crossCount, '#e8b34b'],
            ['Total size', totalSize ? formatBytes(totalSize) : '—'],
          ]
            .filter(Boolean)
            .map(([l, v, color]) => (
              <div className="summary-pill" key={l} style={color ? { color } : undefined}>
                <strong>{v}</strong> {l}
              </div>
            ))}
        </div>
        {crossCount > 0 && (
          <div className="warn-box" id="confirmCrossDriveWarn">
            <strong>Cross-drive move detected</strong>
            <div id="confirmCrossDriveWarnText">
              {crossCount} of {items.length} item(s) will be moved between hard drives — this will take some
              time.
            </div>
          </div>
        )}
        <div className="confirm-list" id="confirmList">
          {items.slice(0, 8).map((i) => {
            const cross = isCrossDriveItem(i)
            const liveTarget = i._liveTarget || i.targetPath || ''
            const src = splitDrive(i.sourcePath || '')
            const dst = splitDrive(liveTarget)
            return (
              <div className="confirm-row" key={i.confirmId}>
                <div className="confirm-row-top">
                  <span className={'badge action-' + i.action}>{i.action === 'replace' ? 'Existing' : 'New'}</span>
                  <span className="c-title" title={liveTarget || i.sourcePath || ''}>
                    {i.title || i.sourceName || ''}
                  </span>
                  <span className="c-size">{i.fileSize ? formatBytes(i.fileSize) : ''}</span>
                  {cross && (
                    <span className="crossdrive-badge" title="Moved between hard drives — will take some time">
                      Cross-drive
                    </span>
                  )}
                </div>
                <div className="confirm-row-paths">
                  <div className="confirm-path" title={i.sourcePath || ''}>
                    <span className="path-mark">FROM</span>
                    <span className={'path-drive' + (cross ? ' diff' : '')}>{src.drive || '/'}</span>
                    <span className="path-rest">{src.rest}</span>
                  </div>
                  <div className="confirm-path" title={liveTarget}>
                    <span className="path-mark">TO</span>
                    <span className={'path-drive' + (cross ? ' diff' : '')}>{dst.drive || '/'}</span>
                    <span className="path-rest">{dst.rest}</span>
                  </div>
                </div>
              </div>
            )
          })}
          {items.length > 8 && (
            <div className="confirm-row" style={{ color: '#9aa4ab', alignItems: 'center' }}>
              +{items.length - 8} more
            </div>
          )}
        </div>
        <div className="modal-actions">
          <button id="confirmModalCancel" onClick={actions.closeConfirmModal}>
            Cancel
          </button>
          <button
            className="primary"
            id="confirmModalStart"
            ref={startRef}
            disabled={state.confirmPosting}
            onClick={() => actions.runConfirm(itemIds)}
          >
            {state.confirmPosting ? 'Starting…' : 'Start Move'}
          </button>
        </div>
      </div>
    </div>
  )
}
