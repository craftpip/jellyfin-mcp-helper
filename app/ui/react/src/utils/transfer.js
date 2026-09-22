// Pure helpers for the bottom-right confirm/copy transfer panel. No DOM access — unit-testable.

export const TRANSFER_DONE_REMOVE_MS = 5000

// Build the initial queue from the confirm batch. Order mirrors the backend's
// processing order (itemIds), which the progress poll consumes one-by-one.
export function buildTransferQueue(itemIds, items) {
  return itemIds
    .map((id) => items.find((i) => i.confirmId === id))
    .filter(Boolean)
    .map((item, order) => ({
      id: 'transfer-' + item.confirmId,
      order,
      confirmId: item.confirmId,
      group: item.title || '',
      kind: item.itemType || '',
      batch: 'running',
      sourcePath: item.sourcePath || '',
      name: item.sourceName || (item.sourcePath || '').split('/').filter(Boolean).pop() || 'file',
      targetPath: item.targetPath || '',
      state: 'queued',
      progress: null,
      doneAt: null,
    }))
}

// Rebuild the queue from the backend's grouped file list (`queue_groups` in
// confirm-progress). Used to restore the transfer panel after a page reload —
// the backend is the source of truth for per-file confirmed/failed flags.
// `order` follows the payload order so the progress poll keeps aligning rows.
export function buildTransferQueueFromGroups(queueGroups, now = Date.now()) {
  const groups = Array.isArray(queueGroups) ? queueGroups : []
  const queue = []
  let order = 0
  groups.forEach((g) => {
    ;(Array.isArray(g && g.items) ? g.items : []).forEach((item) => {
      const sourcePath = item.source_path || ''
      const failed = !!item.failed
      const done = failed || !!item.confirmed
      queue.push({
        id: 'transfer-' + (item.confirm_id || String(order)),
        order: order++,
        confirmId: item.confirm_id || null,
        group: (g && g.group) || '',
        kind: item.kind || (g && g.kind) || '',
        batch: g && g.batch === 'queued' ? 'queued' : 'running',
        sourcePath,
        name: item.source_name || sourcePath.split('/').filter(Boolean).pop() || 'file',
        targetPath: item.target_path || '',
        state: failed ? 'failed' : done ? 'done' : 'queued',
        progress: null,
        doneAt: done ? now : null,
      })
    })
  })
  return queue
}

// Derive the next queue from the latest confirm-progress payload. `prev` tracks
// the monotonic completed/failed counts for this confirm batch so queue items
// stay aligned by their fixed `order` even after done items are removed.
export function deriveTransferQueue(queue, result, prev, now = Date.now()) {
  const completed = Math.max(prev.completed, result.processed ?? 0)
  const failedTotal = result.counts?.failed ?? 0
  const failedDelta = Math.max(0, failedTotal - prev.failed)
  const running = result.status === 'running'
  const overallFailed = result.status === 'failed'

  const finishedOrders = []
  for (let o = prev.completed; o < completed; o++) finishedOrders.push(o)
  const failedOrders = new Set(failedDelta > 0 ? finishedOrders.slice(-failedDelta) : [])

  const currentIdx = queue.findIndex((t) => result.current_file && t.sourcePath === result.current_file)
  const activeIdx = currentIdx !== -1 ? currentIdx : completed

  const updated = queue.map((item) => {
    let state = item.state
    let progress = item.progress
    if (overallFailed && item.order >= completed) {
      state = 'failed'
    } else if (item.order < completed) {
      state = failedOrders.has(item.order) ? 'failed' : 'done'
    } else if (item.order === activeIdx) {
      state = running ? 'copying' : state
      if (running && item.order === currentIdx) {
        progress = {
          percent: result.current_percent,
          speed: result.current_speed,
          speed_bytes: result.current_speed_bytes,
          eta: result.current_eta,
          copied: result.current_copied_bytes,
          size: result.current_size_bytes,
        }
      }
    }
    const finished = state === 'done' || state === 'failed'
    return { ...item, state, progress, doneAt: finished ? item.doneAt || now : null }
  })

  return { queue: updated, state: { completed, failed: failedTotal } }
}
