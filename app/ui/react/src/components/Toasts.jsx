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
      {showTransfer && (
        <TransferPanel
          queue={state.transferQueue}
          summary={state.transferSummary}
          minimized={!!state.transferMinimized}
        />
      )}
    </div>
  )
}

// One persistent box for confirm progress — current file + files queued
// behind it inside a single panel, grouped by show/movie group.
function TransferPanel({ queue, summary, minimized }) {
  const { actions } = useAppStore()
  const total = summary?.total ?? queue.length
  const processed = summary?.processed ?? queue.filter((t) => t.state === 'done' || t.state === 'failed').length
  const percent = summary?.percent ?? (total ? Math.min(100, (processed / total) * 100) : 0)
  const counts = summary?.counts || {}
  const done = summary?.status === 'completed' || summary?.status === 'idle'
  const failed = summary?.status === 'failed'
  const terminal = done || failed
  const title = done ? 'Move completed' : failed ? 'Confirm failed' : 'Moving ' + processed + ' of ' + total
  const queueLength = summary?.queueLength || 0

  const sections = []
  const byGroup = new Map()
  queue.forEach((t) => {
    const key = t.group || ''
    if (!byGroup.has(key)) {
      const section = { group: key, kind: t.kind || '', batch: t.batch || 'running', rows: [] }
      byGroup.set(key, section)
      sections.push(section)
    }
    byGroup.get(key).rows.push(t)
  })
  const active = terminal ? null : queue.find((t) => t.state === 'copying') || queue.find((t) => t.state === 'queued') || null

  if (minimized) {
    return (
      <div className="transfer-panel minimized">
        <div className="transfer-title">
          {!terminal && <span className="transfer-spinner" />}
          {terminal && done && <span className="transfer-tick">✓</span>}
          {terminal && failed && <span className="transfer-fail">✕</span>}
          <span>{title}</span>
          {!terminal && queueLength > 0 && (
            <span className="transfer-queued">
              {' · ' + queueLength + (queueLength === 1 ? ' batch' : ' batches') + ' queued'}
            </span>
          )}
        </div>
        <button
          type="button"
          className="transfer-min-toggle"
          aria-expanded="false"
          aria-label="Expand transfer panel"
          onClick={() => actions.setTransferMinimized(false)}
        >
          ▴
        </button>
      </div>
    )
  }

  return (
    <div className="transfer-panel">
      <div className="transfer-header">
        <div className="transfer-title">
          {title}
          {!terminal && queueLength > 0 && (
            <span className="transfer-queued">
              {' · ' + queueLength + (queueLength === 1 ? ' batch' : ' batches') + ' queued'}
            </span>
          )}
        </div>
        <div className="transfer-header-actions">
          {terminal && (
            <button
              type="button"
              className="transfer-dismiss"
              aria-label="Dismiss transfer panel"
              onClick={() => actions.dismissTransfer()}
            >
              ✕
            </button>
          )}
          <button
            type="button"
            className="transfer-min-toggle"
            aria-expanded="true"
            aria-label="Minimize transfer panel"
            onClick={() => actions.setTransferMinimized(true)}
          >
            ▾
          </button>
        </div>
      </div>
      <div className="transfer-progress">
        <div className="fill" style={{ width: Math.min(percent, 100) + '%' }} />
      </div>
      <div className="transfer-counts">
        Moved: {counts.moved ?? 0} · Replaced: {counts.replaced ?? 0} · Failed: {counts.failed ?? 0}
      </div>
      <div className="transfer-groups">
        {sections.map((section) => (
          <TransferGroup key={section.batch + ':' + section.group} section={section} active={active} />
        ))}
      </div>
    </div>
  )
}

function TransferGroup({ section, active }) {
  return (
    <div className={'transfer-group' + (section.batch === 'queued' ? ' queued-batch' : '')}>
      <div className="transfer-group-header">
        <span className="transfer-group-name" title={section.group}>
          {section.group || 'Files'}
        </span>
        <span className="transfer-group-count">{section.rows.length}</span>
        {section.batch === 'queued' && <span className="transfer-queued-badge">Queued</span>}
      </div>
      <div className="transfer-group-rows">
        {section.rows.map((t) => (
          <TransferRow key={t.id} t={t} isActive={!!active && active.id === t.id} />
        ))}
      </div>
    </div>
  )
}

function TransferRow({ t, isActive }) {
  const upNext = isActive && t.state === 'queued'
  return (
    <div className={'transfer-row ' + t.state + (isActive ? ' active' : '')}>
      {upNext && <div className="transfer-upnext">Up next</div>}
      <div className="transfer-row-line">
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
