import { useAppStore } from '../store/AppStore.jsx'
import { formatBytes } from '../utils/format.js'

const MAX_VISIBLE_QUEUE = 12

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
  const shown = queue.slice(0, MAX_VISIBLE_QUEUE)
  const extra = queue.length - shown.length
  const total = summary?.total ?? queue.length
  const processed = summary?.processed ?? queue.filter((t) => t.state === 'done' || t.state === 'failed').length
  const percent = summary?.percent ?? (total ? Math.min(100, (processed / total) * 100) : 0)
  const counts = summary?.counts || {}
  const done = summary?.status === 'completed' || summary?.status === 'idle'
  const failed = summary?.status === 'failed'

  const title = done ? 'Move completed' : failed ? 'Confirm failed' : 'Moving ' + processed + ' of ' + total

  return (
    <>
      <div className="transfer-header">
        <div className="transfer-title">{title}</div>
        <div className="transfer-progress">
          <div className="fill" style={{ width: Math.min(percent, 100) + '%' }} />
        </div>
        <div className="transfer-counts">
          Moved: {counts.moved ?? 0} · Replaced: {counts.replaced ?? 0} · Failed: {counts.failed ?? 0}
        </div>
      </div>
      <div className="transfer-queue">
        {shown.map((t) => (
          <div key={t.id} className={'transfer-toast ' + t.state}>
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
        ))}
        {extra > 0 && <div className="transfer-extra">+{extra} more in queue</div>}
      </div>
    </>
  )
}
