import { useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { formatBytes } from '../utils/format.js'

export default function Toasts() {
  const { state } = useAppStore()
  const showTransfer = state.transferQueue.length > 0
  const hasAny = showTransfer || state.toasts.length > 0

  if (!hasAny) return null

  return (
    <div className="transfer-toasts" id="transferToasts" role="status" aria-live="polite">
      {state.toasts.map((t) => (
        <div key={t.id} className={'transfer-toast toast-' + t.type} role="status">
          {t.msg}
        </div>
      ))}
      {showTransfer && <TransferToasts queue={state.transferQueue} summary={state.transferSummary} />}
    </div>
  )
}

function TransferToasts({ queue, summary }) {
  const [expanded, setExpanded] = useState(false)
  const total = summary?.total ?? queue.length
  const processed = summary?.processed ?? queue.filter((t) => t.state === 'done' || t.state === 'failed').length
  const percent = summary?.percent ?? (total ? Math.min(100, (processed / total) * 100) : 0)
  const counts = summary?.counts || {}
  const done = summary?.status === 'completed' || summary?.status === 'idle'
  const failed = summary?.status === 'failed'

  const title = done ? 'Move completed' : failed ? 'Confirm failed' : 'Moving ' + processed + ' of ' + total
  const queueLength = summary?.queueLength || 0

  // Drive-style collapsed view: only the file currently moving (or the next
  // queued one before the copy starts), plus a queue count. Terminal states
  // show no live row — the header + counts carry the result.
  const active = done || failed ? null : (queue.find((t) => t.state === 'copying') || queue.find((t) => t.state === 'queued') || null)
  // Files still behind the displayed one (neither done nor on screen).
  const waiting = active ? Math.max(0, total - processed - 1) : 0
  const showWaiting = waiting > 0

  return (
    <>
      <div className="transfer-header">
        <div className="transfer-title">
          {title}
          {!done && !failed && queueLength > 0 && (
            <span className="transfer-queued">
              {' · ' + queueLength + (queueLength === 1 ? ' batch' : ' batches') + ' queued'}
            </span>
          )}
        </div>
        <div className="transfer-progress">
          <div className="fill" style={{ width: Math.min(percent, 100) + '%' }} />
        </div>
        <div className="transfer-counts">
          Moved: {counts.moved ?? 0} · Replaced: {counts.replaced ?? 0} · Failed: {counts.failed ?? 0}
        </div>
      </div>
      <div className={'transfer-queue' + (expanded ? ' expanded' : '')}>
        {active && !expanded && <TransferRow key={active.id} t={active} upNext={active.state !== 'copying'} />}
        {expanded && queue.map((t) => <TransferRow key={t.id} t={t} />)}
        {showWaiting && !expanded && (
          <div className="transfer-waiting">{waiting} file{waiting === 1 ? '' : 's'} in queue</div>
        )}
        {queue.length > 1 && (
          <button
            type="button"
            className="transfer-details-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Show less' : 'Show all ' + total}
          </button>
        )}
      </div>
    </>
  )
}

function TransferRow({ t, upNext }) {
  return (
    <div className={'transfer-toast ' + t.state}>
      {upNext && <div className="transfer-upnext">Up next</div>}
      <div className="transfer-row">
        {t.state === 'copying' && <span className="transfer-spinner" />}
        {t.state === 'done' && <span className="transfer-tick">✓</span>}
        {t.state === 'failed' && <span className="transfer-fail">✕</span>}
        {t.state === 'queued' && <span className="transfer-wait">•</span>}
        <span className="transfer-name" title={t.sourcePath}>
          {t.name}
        </span>
      </div>
      {t.state === 'copying' && (
        <div className="transfer-file">
          <div className="transfer-progress">
            <div className="fill file" style={{ width: Math.min(t.progress?.percent ?? 0, 100) + '%' }} />
          </div>
          {(t.progress?.copied != null || t.progress?.speed || t.progress?.eta) && (
            <div className="transfer-file-meta">
              {t.progress?.copied != null && t.progress?.size != null && (
                <span>
                  {formatBytes(t.progress.copied)} / {formatBytes(t.progress.size)}
                </span>
              )}
              {t.progress?.speed && <span>{t.progress.speed}</span>}
              {t.progress?.eta && <span>ETA {t.progress.eta}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
