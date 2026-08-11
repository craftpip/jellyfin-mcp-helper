import { useState, useEffect } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { fileName, formatBytes, formatDuration, formatConfirmPhase, splitDrive } from '../utils/format.js'
import { isCrossDriveItem } from '../utils/report.js'

export default function ConfirmModal() {
  const { state } = useAppStore()
  const { confirmModal } = state
  if (!confirmModal.open) return null

  if (confirmModal.progress) return <ProgressView progress={confirmModal.progress} />
  return <PreflightView itemIds={confirmModal.itemIds} label={confirmModal.label} />
}

function PreflightView({ itemIds, label }) {
  const { state, actions } = useAppStore()
  const items = itemIds
    .map((id) => state.currentItems.find((i) => i.confirmId === id))
    .filter(Boolean)

  const totalSize = items.reduce((s, i) => s + (Number(i.fileSize) || 0), 0)
  const moveCount = items.filter((i) => i.action === 'move').length
  const replaceCount = items.filter((i) => i.action === 'replace').length
  const crossCount = items.filter((i) => isCrossDriveItem(i)).length

  return (
    <div className="modal-overlay" id="confirmModal">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirmModalTitle">
        <h3 id="confirmModalTitle">Confirm Move — {label || items.length + ' item(s)'}</h3>
        <div className="summary-strip">
          {[
            ['Items', items.length],
            ['Move', moveCount],
            ['Replace', replaceCount],
            crossCount > 0 && ['Cross-drive', crossCount, '#d29922'],
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
            <div className="confirm-row" style={{ color: '#8b949e', alignItems: 'center' }}>
              +{items.length - 8} more
            </div>
          )}
        </div>
        <div className="modal-actions">
          <button id="confirmModalCancel" onClick={actions.closeConfirmModal}>
            Cancel
          </button>
          <button className="primary" id="confirmModalStart" onClick={() => actions.runConfirm(itemIds)}>
            Start Move
          </button>
        </div>
      </div>
    </div>
  )
}

function ProgressView({ progress }) {
  const { actions } = useAppStore()
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const processed = progress.processed ?? 0
  const total = progress.total ?? 0
  const running = progress.status === 'running'
  const done = progress.status === 'completed' || progress.status === 'idle' || progress.status === 'failed'

  const title =
    progress.status === 'failed'
      ? 'Confirm failed'
      : done
        ? 'Confirm completed'
        : 'Moving ' + Math.min(processed + (running ? 1 : 0), total) + ' of ' + total

  // Overall percent blends the finished-item count with the in-flight file copy,
  // so the bar advances while one large cross-drive file is being copied instead
  // of sitting at 0% until the item finishes.
  const itemProgress = total ? processed / total : (progress.percent || 0) / 100
  const fileProgress = running && progress.current_percent != null ? progress.current_percent / 100 : 0
  const overallPercent = Math.min(100, (done ? 1 : itemProgress + fileProgress / Math.max(total, 1)) * 100)

  // Elapsed ticks locally between polls so the counter never appears frozen.
  const lastUpdate = progress.last_update_at ? new Date(progress.last_update_at).getTime() : now
  const liveElapsed = (progress.elapsed_seconds || 0) + (running ? Math.max(0, (now - lastUpdate) / 1000) : 0)

  const metaRows = [
    ['Phase', formatConfirmPhase(progress.phase)],
    ['Overall', processed + '/' + total + ' (' + Math.round(overallPercent) + '%)'],
    ['Elapsed', formatDuration(liveElapsed)],
    progress.eta ? ['Overall ETA', progress.eta] : null,
    progress.counts
      ? [
          'Counts',
          'Moved: ' + (progress.counts.moved || 0) +
          ' · Replaced: ' + (progress.counts.replaced || 0) +
          ' · Failed: ' + (progress.counts.failed || 0),
        ]
      : null,
    progress.last_update_at
      ? ['Last update', new Date(progress.last_update_at).toLocaleTimeString()]
      : null,
  ].filter(Boolean)

  const fileRows = [
    progress.current_file ? ['Source', fileName(progress.current_file)] : null,
    progress.current_target ? ['Target', progress.current_target] : null,
    progress.current_size_bytes != null ? ['Size', formatBytes(progress.current_size_bytes)] : null,
    progress.current_copied_bytes != null
      ? ['Copied', formatBytes(progress.current_copied_bytes)]
      : null,
    progress.current_speed ? ['Speed', progress.current_speed] : null,
    progress.current_eta ? ['File ETA', progress.current_eta] : null,
    progress.current_percent != null
      ? ['File progress', String(progress.current_percent) + '%']
      : null,
  ].filter(Boolean)

  const note =
    progress.note ||
    (progress.cross_drive
      ? 'Cross-drive move — will take some time because the file is being moved between hard drives.'
      : '')

  return (
    <div className="modal-overlay" id="confirmModal">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="confirmModalTitle">
        <h3 id="confirmModalTitle">{title}</h3>
        <div className="progress-bar" style={{ marginTop: '8px' }}>
          <div className="fill" style={{ width: overallPercent + '%', background: '#d29922' }} />
        </div>
        <div className="progress-kv" style={{ marginTop: '8px' }}>
          {metaRows.map(([l, v]) => (
            <div key={l}>
              {l}: <strong>{v}</strong>
            </div>
          ))}
        </div>
        <div className="progress-section" style={{ marginTop: '10px' }}>
          <h3>Current File</h3>
          <div className="progress-bar">
            <div className="fill" style={{ width: Math.min(progress.current_percent || 0, 100) + '%', background: '#58a6ff' }} />
          </div>
          <div className="progress-kv" style={{ marginTop: '6px' }}>
            {fileRows.map(([l, v]) => (
              <div key={l}>
                {l}: <strong>{v}</strong>
              </div>
            ))}
          </div>
        </div>
        {note && <div className="progress-note">{note}</div>}
        <div className="modal-actions">
          <button className="primary" id="confirmModalDone" style={{ display: done ? '' : 'none' }} onClick={actions.closeConfirmModal}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
