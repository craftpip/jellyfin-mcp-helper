import { useEffect } from 'react'

export default function ScanProgressPanel({ progress }) {
  useEffect(() => {
    if (!progress) return
    const panel = document.getElementById('progressPanel')
    if (!panel) return
    const rect = panel.getBoundingClientRect()
    const vh = window.innerHeight || document.documentElement.clientHeight
    if (rect.top >= 0 && rect.bottom <= vh) return
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [!!progress])

  if (!progress) return null

  const waiting = progress.status === 'starting' || (progress.status === 'running' && !progress.total)

  if (waiting) {
    return (
      <div id="progressPanel" className="progress-center progress-starting">
        <span className="spinner" aria-hidden="true" />
        <div className="progress-status">Starting scan...</div>
        <div className="progress-meta">Preparing the scan plan...</div>
      </div>
    )
  }

  const statusLabel =
    progress.status === 'completed'
      ? 'Scan complete'
      : progress.status === 'failed'
        ? 'Scan failed'
        : 'Scanning...'

  const percent = Math.round(progress.percent || 0)

  return (
    <div id="progressPanel" className="progress-center">
      <div className="progress-status">{statusLabel}</div>
      <div className="progress-bar">
        <div className="fill" style={{ width: Math.min(percent, 100) + '%' }} />
      </div>
      <div className="progress-percent">{percent}%</div>
      <div className="progress-meta">
        {progress.processed}/{progress.total} {progress.elapsed ? '· ' + progress.elapsed : ''}
      </div>
      {progress.current_file && (
        <div className="progress-file" title={progress.current_file}>
          {progress.current_file}
        </div>
      )}
    </div>
  )
}
