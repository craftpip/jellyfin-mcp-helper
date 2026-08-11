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

  const info =
    progress.lines ||
    [
      'ID: ' + (progress.scan_id || ''),
      'Status: ' + (progress.status || ''),
      progress.processed !== undefined ? progress.processed + '/' + progress.total : '',
      progress.current_file ? progress.current_file : '',
      progress.elapsed ? progress.elapsed : '',
      progress.eta ? 'ETA: ' + progress.eta : '',
    ].filter(Boolean)

  return (
    <div
      id="progressPanel"
      className={'panel' + (progress.status === 'running' ? ' progress-running' : '')}
    >
      <h2>Progress</h2>
      <div className="progress-bar">
        <div className="fill" style={{ width: Math.min(progress.percent || 0, 100) + '%' }} />
      </div>
      <div className="progress-info">
        {info.map((s, i) => (
          <span key={i}>{s}</span>
        ))}
      </div>
    </div>
  )
}
