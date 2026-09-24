// Pure helpers ported from the legacy panel. No DOM access — unit-testable.
import { isCrossDrive } from './format.js'

// Report item mapping (legacy renderItemsFromReport). Derives title/season/episode
// from the target path.
const EPISODE_TAG_RE = /S\d{2}E\d{2,3}/i
const EPISODE_NUMS_RE = /S(\d{2})E(\d{2,3})/i

function pickKind(item) {
  return item.itemType || item.item_type || ''
}

function pickTarget(item) {
  return item.targetPath || item.target_path || ''
}

function pickExtraType(item) {
  return item.extraType || item.extra_type || ''
}

function pickEpisode(item) {
  if (item.episode) return item.episode
  const m = pickTarget(item).match(EPISODE_TAG_RE)
  return m ? m[0].toUpperCase() : ''
}

// Single source of truth for the "New"/"Existing" action badge. Accepts both
// report shapes (camelCase) and history shapes (snake_case).
export function actionLabelFor(item) {
  return (item.action || 'move') === 'replace' ? 'Existing' : 'New'
}

// Plan 17: only locked skips (in-progress, source-missing, error) are
// Delete-only. Missing `locked` (old payloads/tests) defaults to locked.
export function isLockedItem(item) {
  if (!item || item.action !== 'skip') return false
  return item.locked ?? true
}

// Title/season/episode derived from the target path (shared by actionable
// rows and editable-skip rows, which now carry a proposed target).
function deriveTitleParts(p, itemType, fallbackName) {
  let title = fallbackName || ''
  let season = ''
  let episode = ''
  if ((itemType === 'series' || itemType === 'extra') && p) {
    const parts = p.split('/').filter(Boolean)
    if (itemType === 'series') {
      season = parts.length >= 2 ? parts[parts.length - 2] : ''
      const epMatch = p.match(/S\d{2}E\d{2,3}/i)
      episode = epMatch ? epMatch[0].toUpperCase() : ''
      title = parts.length >= 3 ? parts[parts.length - 3] : (parts[0] || '')
    } else {
      title = parts.length >= 2 ? parts[parts.length - 2] : (parts[0] || '')
    }
  } else if (p) {
    const parts = p.split('/').filter(Boolean)
    title = parts.length >= 2 ? parts[parts.length - 2] : (parts[0] || '')
  }
  return { title, season, episode }
}

// Single source of truth for the "Type" column. Accepts both report shapes
// (camelCase from /scans/current/report) and history shapes (snake_case).
export function typeLabelFor(item) {
  const kind = pickKind(item)
  if (kind === 'series') {
    const ep = pickEpisode(item)
    return ep || 'Series'
  }
  if (kind === 'movie') return 'Movie'
  if (kind === 'extra') {
    const extra = pickExtraType(item)
    return extra ? 'Extra \u00B7 ' + extra : 'Extra'
  }
  return '\u2014'
}

function typeRank(item) {
  const kind = pickKind(item)
  if (kind === 'series') return 0
  if (kind === 'movie') return 1
  if (kind === 'extra') return 2
  return 3
}

function episodeNums(item) {
  const m = pickEpisode(item).match(EPISODE_NUMS_RE) || pickTarget(item).match(EPISODE_NUMS_RE)
  if (!m) return null
  return [Number(m[1]), Number(m[2])]
}

// Ascending within-group order: series by (season, episode) numeric, then
// movies/extras alphabetically by target, stable tiebreak on _idx/confirmId.
export function compareReportItemsAsc(a, b) {
  const ra = typeRank(a)
  const rb = typeRank(b)
  if (ra !== rb) return ra - rb
  if (ra === 0) {
    const na = episodeNums(a)
    const nb = episodeNums(b)
    if (na && nb && (na[0] !== nb[0] || na[1] !== nb[1])) {
      return na[0] !== nb[0] ? na[0] - nb[0] : na[1] - nb[1]
    }
    if ((na && !nb) || (!na && nb)) return na ? -1 : 1
  }
  const ta = (pickTarget(a) || a.sourcePath || a.source_path || '').toLowerCase()
  const tb = (pickTarget(b) || b.sourcePath || b.source_path || '').toLowerCase()
  if (ta !== tb) return ta < tb ? -1 : 1
  const ia = a._idx ?? 0
  const ib = b._idx ?? 0
  if (ia !== ib) return ia - ib
  return String(a.confirmId || a.confirm_id || '') < String(b.confirmId || b.confirm_id || '') ? -1 : 1
}

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
      episode = epMatch ? epMatch[0].toUpperCase() : ''
      title = parts.length >= 3 ? parts[parts.length - 3] : (parts[0] || '')
    } else if (p) {
      const parts = p.split('/').filter(Boolean)
      title = parts.length >= 2 ? parts[parts.length - 2] : (parts[0] || '')
    }

    const extraType = item.extraType || item.extra_type || ''
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
      originalCrossDrive: item.crossDrive || false,
      season,
      episode,
      extraType,
      typeLabel: typeLabelFor({ itemType: item.itemType, episode, targetPath: p, extraType }),
      candidateTargets: item.candidateTargets || [],
      flags: item.flags || [],
      suspect: item.suspect || false,
      corrected: item.corrected || false,
      correctionNote: item.correctionNote || '',
    }
  })

  const skippedMapped = skipped.map((item) => {
    const p = item.targetPath || item.target_path || ''
    const locked = item.locked ?? true
    const kind = item.itemType || item.item_type || 'skip'
    // Editable skips derive a real title from their proposed target so they
    // render/group like actionable rows; locked rows keep the old bucket.
    const parts = !locked && p ? deriveTitleParts(p, kind, item.name) : { title: 'Skipped items', season: '', episode: '' }
    const extraType = item.extraType || item.extra_type || ''
    return {
      confirmId: item.confirmId,
      title: parts.title,
      sourceName: (item.sourcePath || '').split('/').filter(Boolean).pop() || '',
      sourcePath: item.sourcePath || '',
      sourceFolder: item.sourceFolder || (item.containerPath ? item.containerPath.split('/').filter(Boolean).pop() : '') || parts.title,
      containerPath: item.containerPath || '',
      targetPath: p,
      originalTarget: p,
      itemType: kind,
      action: 'skip',
      locked,
      pathExists: item.pathExists || '',
      showFolderExists: item.showFolderExists || false,
      seasonFolderExists: item.seasonFolderExists || false,
      fileExists: item.fileExists || false,
      fileSize: item.fileSize,
      crossDrive: item.crossDrive || false,
      originalCrossDrive: item.crossDrive || false,
      season: parts.season,
      episode: parts.episode || (kind === 'series' && p ? (p.match(/S\d{2}E\d{2,3}/i) || [''])[0].toUpperCase() : ''),
      reason: item.error || item.reason || 'Unknown',
      extraType,
      typeLabel: typeLabelFor({ itemType: kind, episode: parts.episode, targetPath: p, extraType }),
      candidateTargets: item.candidateTargets || [],
      flags: item.flags || [],
      suspect: item.suspect || false,
      corrected: item.corrected || false,
      correctionNote: item.correctionNote || '',
    }
  })

  return mapped.concat(skippedMapped)
}

const GENERIC_FOLDERS = new Set(['downloads', 'torrents', 'download', 'complete', 'incomplete'])

// Group key shared by groupItems and computePathSync. Generic download roots
// (e.g. 'torrents') fall back to title so loose files group/sync solo —
// otherwise unrelated solo titles in the same root look like siblings and
// a solo edit reverts instead of sticking.
function syncGroupKey(item) {
  const raw = item.sourceFolder || item.containerPath?.split('/').filter(Boolean).pop() || item.title || 'Unknown'
  if (GENERIC_FOLDERS.has(String(raw).toLowerCase())) {
    return item.title || 'Unknown'
  }
  return raw
}

export function groupItems(items) {
  const groups = {}
  items.forEach((item, idx) => {
    // Group by source folder (download folder) per plan 12 — all files in one download folder stay together
    // But if the sourceFolder is a generic download root (like 'downloads'), fall back to title
    let key = item.sourceFolder || item.containerPath?.split('/').filter(Boolean).pop() || item.title || 'Unknown'
    if (GENERIC_FOLDERS.has(key.toLowerCase())) {
      key = item.title || 'Unknown'
    }
    if (!groups[key]) {
      groups[key] = { title: key, type: item.itemType, items: [], totalSize: 0, sourceFolder: key, containerPath: item.containerPath || '' }
    }
    groups[key].items.push({ ...item, _idx: idx })
    if (item.fileSize) groups[key].totalSize += Number(item.fileSize)
  })
  const grouped = Object.values(groups)
  // Rows within a group sort ascending (S01E01 before S01E02, series before
  // movies before extras). Group order stays newest-first so incremental scans
  // surface new downloads at the top.
  grouped.forEach((g) => g.items.sort(compareReportItemsAsc))
  grouped.sort((a, b) => {
    const aMax = Math.max(...a.items.map((i) => i._idx ?? 0))
    const bMax = Math.max(...b.items.map((i) => i._idx ?? 0))
    return bMax - aMax
  })
  return grouped
}

// Legacy row filter: free-text search against the row text + action/fileExists axis.
export function itemSearchText(item) {
  return [
    item.title,
    item.episode,
    item.typeLabel,
    item.itemType,
    item.extraType,
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
  if (filterVal === 'suspect' && !item.suspect) match = false
  if (filterVal === 'existing' && !item.fileExists) match = false
  if (filterVal === 'new' && item.fileExists) match = false
  return match
}

// Smart path sync (group-scoped, same key as groupItems). Given the edited row index and new value,
// computes { updates: [{idx, value}...] } for sibling rows whose live path shares
// the same prefix/chunk, or { revert: true } if siblings existed but none matched.
// Solo groups (no other rows in the same rendered group, incl. generic-root
// titles like Lanterns) keep the edit — no revert, no sync, no link icon.
// Per-row link toggle: items with `_linked === false` are excluded from sync
// both as source (editing an unlinked row never syncs) and as target (unlinked rows never receive sync).
export function computePathSync(changedIdx, oldPath, newPath, items) {
  if (oldPath === newPath) return null
  const changedItem = items[changedIdx]
  if (!changedItem) return null
  // Unlinked source → free edit, no sync, no revert
  if (changedItem._linked === false) return null
  const groupKey = syncGroupKey(changedItem)

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

  let hasLinkedSibling = false
  const updates = []
  items.forEach((item, idx) => {
    if (idx === changedIdx) return
    const itemKey = syncGroupKey(item)
    if (itemKey !== groupKey) return
    // Unlinked targets are skipped entirely — they neither count as sibling nor receive updates
    if (item._linked === false) return
    hasLinkedSibling = true
    const livePath = item._liveTarget || item.targetPath
    if (!livePath.startsWith(prefix)) return
    const after = livePath.slice(i1)
    const replaced = after.replace(oldChunk, newChunk)
    if (replaced === after) return
    updates.push({ idx, value: prefix + replaced })
  })

  if (!hasLinkedSibling) return null
  if (updates.length === 0) return { revert: true }
  return { updates }
}

// Diff a fresh report against the previously shown items (matched by source
// path). "New" = source never shown before; "updated" = known source with a
// changed action/target (e.g. skip -> move after an undo-revive, retarget).
// newSources feeds bringNewGroupsToTop so fresh groups render first.
export function summarizeReportDiff(prevItems, nextItems) {
  const prevBySource = new Map()
  ;(prevItems || []).forEach((i) => {
    const key = i.sourcePath || i.source_path || ''
    if (key && !prevBySource.has(key)) prevBySource.set(key, i)
  })
  let newCount = 0
  let updatedCount = 0
  const newSources = new Set()
  ;(nextItems || []).forEach((i) => {
    const key = i.sourcePath || i.source_path || ''
    if (!key) return
    const prev = prevBySource.get(key)
    if (!prev) {
      newCount += 1
      newSources.add(key)
    } else {
      const prevTarget = prev.targetPath ?? prev.target_path ?? ''
      const nextTarget = i.targetPath ?? i.target_path ?? ''
      if ((prev.action || '') !== (i.action || '') || prevTarget !== nextTarget) updatedCount += 1
    }
  })
  return { newCount, updatedCount, newSources }
}

// Stable reorder: groups containing freshly found sources render at the top,
// preserving relative order otherwise. No-op when nothing is new.
export function bringNewGroupsToTop(groups, newSources) {
  if (!newSources || newSources.size === 0 || !groups) return groups
  const hasNew = (g) => (g.items || []).some((i) => newSources.has(i.sourcePath || i.source_path || ''))
  const fresh = groups.filter(hasNew)
  if (fresh.length === 0) return groups
  return [...fresh, ...groups.filter((g) => !hasNew(g))]
}

// Split a full target path into its library-root prefix (slash-terminated)
// and the remainder after it. Longest-prefix match wins so nested roots
// resolve to the most specific one. Roots may be strings or
// {path} objects (GET /api/browse/roots shape).
// No match → { root: '', remainder: fullPath } (custom path, nothing lost).
export function splitTarget(fullPath, roots) {
  const value = fullPath || ''
  const list = (roots || [])
    .map((r) => (typeof r === 'string' ? r : r && r.path))
    .filter(Boolean)
  let best = ''
  for (const raw of list) {
    const root = raw.replace(/\/+$/, '')
    if (!root) continue
    if (value === raw || value === root) {
      if (root.length > best.length) best = root
    } else if (value.startsWith(root + '/')) {
      if (root.length > best.length) best = root
    }
  }
  if (!best) return { root: '', remainder: value }
  const prefix = best + '/'
  return { root: prefix, remainder: value === best || value === best + '/' ? '' : value.slice(prefix.length) }
}

// Join a slash-terminated root with a remainder. Leading slashes on the
// remainder are stripped so typing "/x/y" never escapes the root.
export function joinTarget(root, remainder) {
  if (!root) return remainder || ''
  const prefix = root.endsWith('/') ? root : root + '/'
  const rem = (remainder || '').replace(/^\/+/, '')
  return prefix + rem
}

// Default selection on report render: every actionable item checked, skipped unchecked.
export function defaultSelection(items) {
  return items.filter((i) => i.action !== 'skip').map((i) => i.confirmId)
}

// Cross-drive check using the live (edited) target path. The backend-computed
// flag reflects the target at scan time and goes stale once the target is edited
// in the UI (e.g. /media3 -> /media2). So: when the target was changed, judge by
// drive roots only; otherwise trust the original backend flag (real device check).
// Uses originalCrossDrive (preserved from scan) instead of mutated crossDrive to
// avoid stale true after a revert (media3→media2→media3).
// Shared by ReportPanel and HistoryPage — accepts camelCase (report) and
// snake_case (history) shapes so both UIs judge cross-drive identically.
export function isCrossDriveItem(item) {
  const source = item.sourcePath ?? item.source_path ?? ''
  const target = item.targetPath ?? item.target_path ?? ''
  const original = item.originalTarget ?? item.target_path ?? item.targetPath ?? ''
  const live = item._liveTarget || target
  const changed = !!(item._liveTarget && item._liveTarget !== original)
  if (changed) return isCrossDrive(source, live)
  const orig = item.originalCrossDrive ?? item.crossDrive ?? item.cross_drive
  return !!(orig || isCrossDrive(source, live))
}
