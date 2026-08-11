export function formatBytes(bytes) {
  if (bytes === undefined || bytes === null) return ''
  let size = Number(bytes)
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let idx = 0
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024
    idx += 1
  }
  return (idx === 0 ? Math.round(size) : size.toFixed(1)) + ' ' + units[idx]
}

export function formatConfirmPhase(phase) {
  return {
    idle: 'Idle',
    preparing: 'Preparing',
    stopping_seeding: 'Stopping seeding',
    moving: 'Copying or moving',
    deleting_source: 'Removing source',
    triggering_jellyfin: 'Triggering Jellyfin scan',
    completed: 'Completed',
    failed: 'Failed',
  }[phase] || 'Running'
}

export function fileName(path) {
  return path ? path.split('/').pop() : ''
}

export function escHtml(s) {
  const d = document.createElement('div')
  d.textContent = s
  return d.innerHTML
}
