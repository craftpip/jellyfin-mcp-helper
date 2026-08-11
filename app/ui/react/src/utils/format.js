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

export function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return ''
  const s = Math.floor(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return h + 'h ' + m + 'm ' + sec + 's'
  if (m > 0) return m + 'm ' + sec + 's'
  return sec + 's'
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

// Drive root = first path segment (mirrors the backend's mount label for /mediaN paths).
export function driveRoot(path) {
  if (!path) return ''
  const m = path.match(/^(\/[^/]+)/)
  return m ? m[1] : ''
}

// True when source and target live under different drive roots.
export function isCrossDrive(sourcePath, targetPath) {
  const s = driveRoot(sourcePath)
  const t = driveRoot(targetPath)
  return !!s && !!t && s !== t
}

// Split a path into its drive root and the rest, so the root can be highlighted.
export function splitDrive(path) {
  if (!path) return { drive: '', rest: '' }
  const m = path.match(/^(\/[^/]+)(\/.*)?$/)
  return m ? { drive: m[1], rest: m[2] || '' } : { drive: '', rest: path }
}

export function escHtml(s) {
  const d = document.createElement('div')
  d.textContent = s
  return d.innerHTML
}
