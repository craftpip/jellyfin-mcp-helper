// Pure helpers ported from the legacy panel. No DOM access — unit-testable.
import { isCrossDrive } from './format.js'

// Report item mapping (legacy renderItemsFromReport). Derives title/season/episode
// from the target path.
export function mapReportItems(report) {
  const allItems = report.items || []
  const actionable = allItems.filter((i) => i.action === 'move' || i.action === 'replace')
  const skipped = allItems.filter((i) => i.action === 'skip')

  const mapped = actionable.map((item) => {
    const isSeries = item.itemType === 'series'
    const p = item.targetPath || ''
    let title = item.name || ''
    let season = ''
    let episode = ''

    if (isSeries && p) {
      const parts = p.split('/').filter(Boolean)
      season = parts.length >= 2 ? parts[parts.length - 2] : ''
      const epMatch = p.match(/S\d{2}E\d{2,3}/i)
      episode = epMatch ? epMatch[0] : ''
      title = parts.length >= 3 ? parts[parts.length - 3] : (parts[0] || '')
    } else if (p) {
      const parts = p.split('/').filter(Boolean)
      title = parts.length >= 2 ? parts[parts.length - 2] : (parts[0] || '')
    }

    return {
      confirmId: item.confirmId,
      title,
      sourceName: (item.sourcePath || '').split('/').filter(Boolean).pop() || '',
      sourcePath: item.sourcePath || '',
      sourceFolder: item.sourceFolder || (item.containerPath ? item.containerPath.split('/').filter(Boolean).pop() : '') || title,
      containerPath: item.containerPath || '',
      targetPath: p,
      originalTarget: p,
      itemType: item.itemType,
      action: item.action || 'move',
      pathExists: item.pathExists || '',
      fileExists: item.fileExists || false,
      fileSize: item.fileSize,
      crossDrive: item.crossDrive || false,
      season,
      episode,
      candidateTargets: item.candidateTargets || [],
      flags: item.flags || [],
      suspect: item.suspect || false,
      corrected: item.corrected || false,
      correctionNote: item.correctionNote || '',
    }
  })

  const skippedMapped = skipped.map((item) => ({
    confirmId: item.confirmId,
    title: 'Skipped items',
    sourceName: (item.sourcePath || '').split('/').filter(Boolean).pop() || '',
    sourcePath: item.sourcePath || '',
    sourceFolder: item.sourceFolder || (item.containerPath ? item.containerPath.split('/').filter(Boolean).pop() : '') || 'Skipped items',
    containerPath: item.containerPath || '',
    targetPath: '',
    originalTarget: '',
    itemType: item.itemType || 'skip',
    action: 'skip',
    pathExists: '',
    fileExists: false,
    fileSize: item.fileSize,
    reason: item.error || item.reason || 'Unknown',
  }))

  return mapped.concat(skippedMapped)
}

export function groupItems(items) {
  const groups = {}
  items.forEach((item, idx) => {
    // Group by source folder (torrent folder) per plan 12 — all files in one torrent folder stay together
    const key = item.sourceFolder || item.containerPath?.split('/').filter(Boolean).pop() || item.title || 'Unknown'
    if (!groups[key]) {
      groups[key] = { title: key, type: item.itemType, items: [], totalSize: 0, sourceFolder: key, containerPath: item.containerPath || '' }
    }
    groups[key].items.push({ ...item, _idx: idx })
    if (item.fileSize) groups[key].totalSize += Number(item.fileSize)
  })
  return Object.values(groups)
}

// Legacy row filter: free-text search against the row text + action/fileExists axis.
export function itemSearchText(item) {
  return [
    item.title,
    item.episode,
    item.sourceName,
    item.sourcePath,
    item.targetPath,
    item.reason,
  ].filter(Boolean).join(' ').toLowerCase()
}

export function matchesFilter(item, query, filterVal) {
  let match = true
  if (query && !itemSearchText(item).includes(query.toLowerCase())) match = false
  if (filterVal === 'move' && item.action !== 'move') match = false
  if (filterVal === 'replace' && item.action !== 'replace') match = false
  if (filterVal === 'extra' && item.itemType !== 'extra') match = false
  if (filterVal === 'existing' && !item.fileExists) match = false
  if (filterVal === 'new' && item.fileExists) match = false
  return match
}

// Legacy smart path sync (group-scoped). Given the edited row index and new value,
// computes { updates: [{idx, value}...] } for sibling rows whose live path shares
// the same prefix/chunk, or { revert: true } if siblings existed but none matched.
// Solo groups (no other rows with the same title) keep the edit — no revert, no sync.
export function computePathSync(changedIdx, oldPath, newPath, items) {
  if (oldPath === newPath) return null
  const changedItem = items[changedIdx]
  if (!changedItem) return null
  const groupTitle = changedItem.title

  let i1 = 0
  while (i1 < oldPath.length && i1 < newPath.length && oldPath[i1] === newPath[i1]) i1++

  let i2 = 0
  while (
    i2 + i1 < oldPath.length &&
    i2 + i1 < newPath.length &&
    oldPath[oldPath.length - 1 - i2] === newPath[newPath.length - 1 - i2]
  ) i2++

  const prefix = oldPath.slice(0, i1)
  const oldChunk = oldPath.slice(i1, oldPath.length - i2)
  const newChunk = newPath.slice(i1, newPath.length - i2)
  if (oldChunk === newChunk) return null

  let hasSameGroupSibling = false
  const updates = []
  items.forEach((item, idx) => {
    if (idx === changedIdx) return
    if (item.title !== groupTitle) return
    hasSameGroupSibling = true
    const livePath = item._liveTarget || item.targetPath
    if (!livePath.startsWith(prefix)) return
    const after = livePath.slice(i1)
    const replaced = after.replace(oldChunk, newChunk)
    if (replaced === after) return
    updates.push({ idx, value: prefix + replaced })
  })

  if (!hasSameGroupSibling) return null
  if (updates.length === 0) return { revert: true }
  return { updates }
}

// Default selection on report render: every actionable item checked, skipped unchecked.
export function defaultSelection(items) {
  return items.filter((i) => i.action !== 'skip').map((i) => i.confirmId)
}

// Cross-drive check using the live (edited) target path. The backend-computed
// flag reflects the target at scan time and goes stale once the target is edited
// in the UI (e.g. /media3 -> /media2). So: when the target was changed, judge by
// drive roots only; otherwise trust the backend flag (real device check) first.
export function isCrossDriveItem(item) {
  const live = item._liveTarget || item.targetPath || ''
  const changed = !!(item._liveTarget && item._liveTarget !== item.originalTarget)
  if (changed) return isCrossDrive(item.sourcePath, live)
  return !!(item.crossDrive || isCrossDrive(item.sourcePath, live))
}
