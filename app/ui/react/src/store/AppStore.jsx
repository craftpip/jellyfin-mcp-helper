import { createContext, useContext, useEffect, useReducer, useRef } from 'react'
import { mcpCall, mcpListTools } from '../mcp/mcpClient.js'
import { computePathSync, defaultSelection, groupItems, isCrossDriveItem, mapReportItems } from '../utils/report.js'

const AppStoreContext = createContext(null)

const POLL_INTERVAL_MS = 2000
const LOG_LIMIT = 1000

const initialState = {
  connStatus: 'connecting',
  connMessage: 'connecting...',
  jellyfinLibraries: [],
  libraryScanning: null,
  scanId: null,
  scanRunning: false,
  scanProgress: null,
  reportVisible: false,
  reportAll: [],
  reportSummary: null,
  currentItems: [],
  reportGroups: [],
  currentFilter: 'all',
  rowLimit: 100,
  selectedIds: [],
  expandedGroups: [],
  confirmActive: false,
  confirmButtonLabel: 'Confirm Selected',
  confirmModal: { open: false, itemIds: [], label: '', progress: null },
  logEntries: [],
  toasts: [],
}

function toggleInList(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_CONN':
      return { ...state, connStatus: action.status, connMessage: action.message }
    case 'SET_LIBRARIES':
      return { ...state, jellyfinLibraries: action.libraries }
    case 'SET_LIBRARY_SCANNING':
      return { ...state, libraryScanning: action.name }
    case 'SET_SCAN_ID':
      return { ...state, scanId: action.scanId }
    case 'SET_SCAN_RUNNING':
      return { ...state, scanRunning: action.scanRunning }
    case 'SET_SCAN_PROGRESS':
      return { ...state, scanProgress: action.progress }
    case 'SET_CONFIRM_ACTIVE':
      return { ...state, confirmActive: action.confirmActive }
    case 'SET_CONFIRM_BUTTON_LABEL':
      return { ...state, confirmButtonLabel: action.label }
    case 'SET_CONFIRM_MODAL':
      return { ...state, confirmModal: action.modal }
    case 'SET_REPORT':
      return { ...state, ...action.payload }
    case 'SET_SELECTION':
      return { ...state, selectedIds: action.selectedIds }
    case 'SET_ITEMS':
      return { ...state, currentItems: action.currentItems, reportGroups: action.reportGroups }
    case 'SET_FILTER':
      return { ...state, currentFilter: action.filter }
    case 'TOGGLE_GROUP':
      return { ...state, expandedGroups: toggleInList(state.expandedGroups, action.gid) }
    case 'SET_GROUPS_EXPANDED':
      return { ...state, expandedGroups: action.list }
    case 'ADD_LOG':
      return { ...state, logEntries: [...state.logEntries, action.entry].slice(-LOG_LIMIT) }
    case 'ADD_TOAST':
      return { ...state, toasts: [...state.toasts, action.toast] }
    case 'REMOVE_TOAST':
      return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) }
    default:
      return state
  }
}

let toastSeq = 0

export function AppStoreProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const stateRef = useRef(state)
  stateRef.current = state
  const timers = useRef({ scanPoll: null, confirmPoll: null, paste: null })
  const didInit = useRef(false)

  // ---- feedback primitives ----
  function toast(msg, type = 'info') {
    const id = ++toastSeq
    dispatch({ type: 'ADD_TOAST', toast: { id, msg, type } })
    setTimeout(() => dispatch({ type: 'REMOVE_TOAST', id }), 3500)
  }

  function log(msg, type = 'info') {
    dispatch({ type: 'ADD_LOG', entry: { msg, type } })
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text)
      toast('Copied: ' + text, 'good')
    } catch (e) {
      toast('Failed to copy', 'err')
    }
  }

  // ---- report rendering ----
  function renderReport(report) {
    const all = mapReportItems(report)
    const s = report.summary || {}
    const limit = stateRef.current.rowLimit > 0 ? stateRef.current.rowLimit : all.length
    const sliced = all.slice(0, limit)
    const withLive = sliced.map((i) => ({ ...i, _liveTarget: i.targetPath }))
    const groups = groupItems(withLive)
    dispatch({
      type: 'SET_REPORT',
      payload: {
        reportVisible: true,
        reportAll: all,
        reportSummary: s,
        currentItems: withLive,
        reportGroups: groups,
        currentFilter: 'all',
        selectedIds: defaultSelection(withLive),
        expandedGroups: groups.map((g, gi) => 'group-' + gi),
        scanId: s.scan_id || stateRef.current.scanId,
      },
    })
  }

  async function fetchReport() {
    const scanId = stateRef.current.scanId
    try {
      const result = await mcpCall('get move new downloads scan report', scanId ? { scanId } : {})
      if (!result || result.hint) {
        if (scanId) log(result?.hint || 'No scan report available', 'warn')
        dispatch({ type: 'SET_SCAN_ID', scanId: null })
        dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
        dispatch({ type: 'SET_REPORT', payload: { reportVisible: false } })
        return
      }
      if (result.progress) {
        log('Scan is still running — check progress first', 'warn')
        return
      }
      dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
      if (result.summary?.scan_id) dispatch({ type: 'SET_SCAN_ID', scanId: result.summary.scan_id })
      renderReport(result)
      log('Report loaded — ' + (result.summary?.action_required || 0) + ' actions pending', 'good')
    } catch (e) {
      log('Report error: ' + e.message, 'err')
      toast('Report error: ' + e.message, 'err')
    }
  }

  // ---- connection ----
  async function checkConnection() {
    try {
      const tools = await mcpListTools()
      if (tools.length) {
        dispatch({ type: 'SET_CONN', status: 'connected', message: 'connected (' + tools.length + ' tools)' })
        log('Connected — found ' + tools.length + ' MCP tools', 'good')
        try {
          const libs = await mcpCall('get available jellyfin libraries list')
          const libraries = libs.libraries || []
          dispatch({ type: 'SET_LIBRARIES', libraries })
          log('Loaded ' + libraries.length + ' libraries', 'good')
          fetchReport()
        } catch (e) {
          log('Could not load libraries: ' + e.message, 'warn')
        }
      }
    } catch (e) {
      dispatch({ type: 'SET_CONN', status: 'error', message: 'error: ' + e.message })
      log('Connection failed: ' + e.message, 'err')
    }
  }

  async function triggerLibraryScan(name) {
    dispatch({ type: 'SET_LIBRARY_SCANNING', name })
    log('Triggering Jellyfin library scan for: ' + name, 'info')
    toast('Scanning ' + name + '...', 'info')
    try {
      const result = await mcpCall('trigger jellyfin library scan', { libraryName: name })
      log('Library scan triggered: ' + (result.message || ''), 'good')
      toast('Scan triggered for ' + name, 'good')
    } catch (e) {
      log('Library scan error: ' + e.message, 'err')
      toast('Scan error: ' + e.message, 'err')
    } finally {
      dispatch({ type: 'SET_LIBRARY_SCANNING', name: null })
    }
  }

  // ---- scan ----
  async function startScan() {
    if (stateRef.current.scanRunning || stateRef.current.confirmActive) return
    dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: true })
    log('Starting scan...', 'info')
    if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
    dispatch({
      type: 'SET_SCAN_PROGRESS',
      progress: {
        percent: 0,
        status: 'starting',
        lines: ['Starting scan...', 'Waiting for backend to create the scan plan'],
      },
    })
    try {
      const result = await mcpCall('move new downloads scan')
      const scanId = result.scan_id || null
      dispatch({ type: 'SET_SCAN_ID', scanId })
      log('Scan started! ID: ' + scanId + ' — ' + (result.message || ''), 'good')
      toast('Scan started', 'good')
      log(
        'Progress: ' + result.processed + '/' + result.total + ' (' + (result.percent || 0) + '%)',
        'info'
      )
      dispatch({ type: 'SET_SCAN_PROGRESS', progress: result })
      await pollScanProgress()
    } catch (e) {
      log('Scan error: ' + e.message, 'err')
      toast('Scan error: ' + e.message, 'err')
      dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
    }
  }

  async function pollScanProgress() {
    try {
      const result = await mcpCall(
        'get move new downloads scan progress',
        stateRef.current.scanId ? { scanId: stateRef.current.scanId } : {}
      )
      if (!result || result.hint) {
        log(result?.hint || 'No active scan found', 'warn')
        dispatch({ type: 'SET_SCAN_PROGRESS', progress: null })
        dispatch({ type: 'SET_SCAN_ID', scanId: null })
        dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
        return
      }
      if (result.status === 'running' || result.status === 'completed') {
        log('Progress: ' + result.processed + '/' + result.total + ' (' + (result.percent || 0) + '%)', 'info')
        if (result.current_file) log('  File: ' + result.current_file, 'info')
      }
      if (result.scan_id) dispatch({ type: 'SET_SCAN_ID', scanId: result.scan_id })
      dispatch({ type: 'SET_SCAN_PROGRESS', progress: result })

      if (result.status === 'completed') {
        dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
        toast('Scan completed — loading report...', 'good')
        dispatch({ type: 'SET_SCAN_PROGRESS', progress: null })
        setTimeout(fetchReport, 500)
      } else if (result.status === 'running') {
        if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
        timers.current.scanPoll = setTimeout(pollScanProgress, POLL_INTERVAL_MS)
      }
    } catch (e) {
      log('Progress error: ' + e.message, 'err')
    }
  }

  // ---- report controls ----
  function setFilter(key) {
    dispatch({ type: 'SET_FILTER', filter: key })
  }

  function setRowLimit(value) {
    const items = stateRef.current.reportAll
    const sliced = value > 0 ? items.slice(0, value) : items
    const withLive = sliced.map((i) => ({ ...i, _liveTarget: i.targetPath }))
    const groups = groupItems(withLive)
    dispatch({
      type: 'SET_REPORT',
      payload: {
        currentItems: withLive,
        reportGroups: groups,
        selectedIds: defaultSelection(withLive),
        expandedGroups: groups.map((g, gi) => 'group-' + gi),
        rowLimit: value,
      },
    })
  }

  function toggleGroup(gid) {
    dispatch({ type: 'TOGGLE_GROUP', gid })
  }

  function toggleAllGroups(expand) {
    const groups = stateRef.current.reportGroups
    dispatch({ type: 'SET_GROUPS_EXPANDED', list: expand ? groups.map((g, gi) => 'group-' + gi) : [] })
  }

  // ---- selection ----
  function selectItem(confirmId, checked) {
    const ids = new Set(stateRef.current.selectedIds)
    if (checked) ids.add(confirmId)
    else ids.delete(confirmId)
    dispatch({ type: 'SET_SELECTION', selectedIds: [...ids] })
  }

  function toggleGroupSelect(gi, checked) {
    const group = stateRef.current.reportGroups?.[gi]
    if (!group) return
    const ids = new Set(stateRef.current.selectedIds)
    group.items.forEach((item) => {
      if (checked) ids.add(item.confirmId)
      else ids.delete(item.confirmId)
    })
    dispatch({ type: 'SET_SELECTION', selectedIds: [...ids] })
  }

  function setCheckedItems(mode) {
    const items = stateRef.current.currentItems
    const actionable = items.filter((i) => i.action !== 'skip')
    const skipIds = items.filter((i) => i.action === 'skip').map((i) => i.confirmId)
    let selected = skipIds
    if (mode === 'all') selected = skipIds.concat(actionable.map((i) => i.confirmId))
    else if (mode === 'existing') selected = skipIds.concat(actionable.filter((i) => i.fileExists).map((i) => i.confirmId))
    else if (mode === 'move') selected = skipIds.concat(actionable.filter((i) => i.action === 'move').map((i) => i.confirmId))
    else if (mode === 'replace') selected = skipIds.concat(actionable.filter((i) => i.action === 'replace').map((i) => i.confirmId))
    dispatch({ type: 'SET_SELECTION', selectedIds: selected })
  }

  // ---- target path editing + smart sync ----
  function onTargetInputChange(idx, value, fromPaste = false) {
    const apply = () => {
      const items = stateRef.current.currentItems
      const item = items[idx]
      if (!item) return
      const oldPath = item._liveTarget || item.targetPath
      const updated = [...items]
      updated[idx] = { ...item, _liveTarget: value, crossDrive: isCrossDriveItem({ ...item, _liveTarget: value }) }
      const sync = computePathSync(idx, oldPath, value, updated)
      if (sync) {
        if (sync.revert) {
          updated[idx] = { ...updated[idx], _liveTarget: oldPath, crossDrive: isCrossDriveItem({ ...updated[idx], _liveTarget: oldPath }) }
        } else {
          sync.updates.forEach((u) => {
            const sibling = updated[u.idx]
            updated[u.idx] = {
              ...sibling,
              _liveTarget: u.value,
              crossDrive: isCrossDriveItem({ ...sibling, _liveTarget: u.value }),
            }
          })
        }
      }
      dispatch({ type: 'SET_ITEMS', currentItems: updated, reportGroups: groupItems(updated) })
    }
    if (fromPaste) {
      if (timers.current.paste) clearTimeout(timers.current.paste)
      timers.current.paste = setTimeout(apply, 0)
    } else {
      apply()
    }
  }

  async function applyGroupTargetEdits(gi) {
    const group = stateRef.current.reportGroups?.[gi]
    if (!group) return
    const updates = []
    group.items.forEach((item) => {
      const live = item._liveTarget || item.targetPath
      if (live.trim() !== item.originalTarget) {
        updates.push({ confirmId: item.confirmId, targetPath: live.trim() })
      }
    })
    if (!updates.length) {
      toast('No paths changed in this group', 'info')
      return
    }
    try {
      await mcpCall('update move new downloads scan', {
        scanId: stateRef.current.scanId,
        items: updates,
      })
      log('Updated ' + updates.length + ' paths in "' + group.title + '"', 'good')
      toast('Paths updated in "' + group.title + '"', 'good')
      const items = stateRef.current.currentItems.map((item) => {
        const u = updates.find((x) => x.confirmId === item.confirmId)
        if (u) {
          const applied = { ...item, targetPath: u.targetPath, originalTarget: u.targetPath, _liveTarget: u.targetPath }
          return { ...applied, crossDrive: isCrossDriveItem(applied) }
        }
        return item
      })
      dispatch({ type: 'SET_ITEMS', currentItems: items, reportGroups: groupItems(items) })
    } catch (e) {
      log('Update error: ' + e.message, 'err')
      toast('Update error: ' + e.message, 'err')
    }
  }

  // ---- confirm ----
  function openConfirmModal(itemIds, label) {
    if (stateRef.current.confirmActive) {
      toast('A move is already running — wait for it to finish', 'info')
      return
    }
    dispatch({ type: 'SET_CONFIRM_MODAL', modal: { open: true, itemIds, label, progress: null } })
  }

  function closeConfirmModal() {
    dispatch({ type: 'SET_CONFIRM_MODAL', modal: { open: false, itemIds: [], label: '', progress: null } })
  }

  function confirmSelected() {
    const ids = stateRef.current.selectedIds.filter((id) => {
      const item = stateRef.current.currentItems.find((i) => i.confirmId === id)
      return item && item.action !== 'skip'
    })
    if (!ids.length) {
      toast('No move/replace items selected (skipped items are not movable)', 'info')
      return
    }
    if (stateRef.current.confirmActive) {
      toast('A move is already running — wait for it to finish', 'info')
      return
    }
    openConfirmModal(ids, 'selected items')
  }

  function confirmGroup(gi) {
    const group = stateRef.current.reportGroups?.[gi]
    if (!group) return
    const ids = []
    group.items.forEach((item) => {
      if (item.action === 'skip') return
      if (stateRef.current.selectedIds.includes(item.confirmId)) ids.push(item.confirmId)
    })
    if (!ids.length) {
      toast('Select at least one item in this group', 'info')
      return
    }
    if (stateRef.current.confirmActive) {
      toast('A move is already running — wait for it to finish', 'info')
      return
    }
    openConfirmModal(ids, '"' + group.title + '"')
  }

  async function runConfirm(itemIds) {
    try {
      dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: true })
      if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
      dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm running...' })
      dispatch({
        type: 'SET_CONFIRM_MODAL',
        modal: {
          open: true,
          itemIds,
          label: 'selected items',
          progress: { status: 'running', phase: 'preparing', processed: 0, total: itemIds.length },
        },
      })
      log('Confirming ' + itemIds.length + ' item(s)...', 'info')
      const result = await mcpCall('confirm move new downloads scan', {
        scanId: stateRef.current.scanId,
        itemIds,
      })
      log('Confirm started! ID: ' + stateRef.current.scanId, 'good')
      toast('Confirm started in background', 'good')
      dispatch({
        type: 'SET_CONFIRM_MODAL',
        modal: { open: true, itemIds, label: 'selected items', progress: result },
      })
      pollConfirmProgress()
    } catch (e) {
      log('Confirm error: ' + e.message, 'err')
      toast('Confirm error: ' + e.message, 'err')
      dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
      dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
      closeConfirmModal()
    }
  }

  async function pollConfirmProgress() {
    if (!stateRef.current.confirmActive) return
    try {
      const result = await mcpCall(
        'get move new downloads confirm progress',
        stateRef.current.scanId ? { scanId: stateRef.current.scanId } : {}
      )
      const p = result.processed ?? 0
      const t = result.total ?? 0
      log('Confirm progress: ' + p + '/' + t + ' (' + (result.status || 'unknown') + ')', 'info')
      dispatch({
        type: 'SET_CONFIRM_MODAL',
        modal: { open: true, itemIds: stateRef.current.confirmModal.itemIds, label: '', progress: result },
      })

      if (result.status === 'completed' || result.status === 'idle') {
        dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
        dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
        const moved = result.counts?.moved || 0
        const replaced = result.counts?.replaced || 0
        const failed = result.counts?.failed || 0
        log('Confirm completed. Moved: ' + moved + ', Replaced: ' + replaced + ', Failed: ' + failed, 'good')
        toast('Confirm completed! Moved: ' + moved + ', Replaced: ' + replaced + ', Failed: ' + failed, 'good')
        setTimeout(fetchReport, 800)
        return
      }
      if (result.status === 'failed') {
        dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
        dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
        return
      }
      if (result.status === 'running') {
        dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Moving ' + p + '/' + t + '...' })
      }
    } catch (e) {
      log('Confirm progress error: ' + e.message, 'err')
    }
    if (stateRef.current.confirmActive) {
      if (timers.current.confirmPoll) clearTimeout(timers.current.confirmPoll)
      timers.current.confirmPoll = setTimeout(pollConfirmProgress, POLL_INTERVAL_MS)
    }
  }

  // ---- delete source ----
  async function deleteSourceItem(idx) {
    const item = stateRef.current.currentItems[idx]
    if (!item) return
    if (stateRef.current.confirmActive) {
      toast('Wait for the current move to finish first', 'info')
      return
    }
    const source = item.sourcePath || item.sourceName || ''
    const ok = window.confirm(
      'Delete the source download file permanently?\n\n' +
        source +
        '\n\nThe file will be removed from your downloads and skipped from the move plan. This cannot be undone.'
    )
    if (!ok) return
    try {
      await mcpCall('delete move new downloads scan items', {
        scanId: stateRef.current.scanId,
        itemIds: [item.confirmId],
      })
      log('Deleted source file: ' + source, 'good')
      toast('Deleted: ' + (item.sourceName || 'file'), 'good')
      fetchReport()
    } catch (e) {
      log('Delete error: ' + e.message, 'err')
      toast('Delete error: ' + e.message, 'err')
    }
  }

  async function deleteSelectedSkipped(gi) {
    const group = stateRef.current.reportGroups?.[gi]
    if (!group) return
    const ids = group.items.filter((i) => stateRef.current.selectedIds.includes(i.confirmId)).map((i) => i.confirmId)
    if (!ids.length) {
      toast('Select at least one skipped item to delete', 'info')
      return
    }
    if (stateRef.current.confirmActive) {
      toast('Wait for the current move to finish first', 'info')
      return
    }
    const ok = window.confirm('Delete ' + ids.length + ' source file(s) permanently? This cannot be undone.')
    if (!ok) return
    try {
      await mcpCall('delete move new downloads scan items', {
        scanId: stateRef.current.scanId,
        itemIds: ids,
      })
      log('Deleted ' + ids.length + ' skipped source file(s)', 'good')
      toast('Deleted ' + ids.length + ' skipped file(s)', 'good')
      fetchReport()
    } catch (e) {
      log('Delete error: ' + e.message, 'err')
      toast('Delete error: ' + e.message, 'err')
    }
  }

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    checkConnection()
    return () => {
      if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
      if (timers.current.confirmPoll) clearTimeout(timers.current.confirmPoll)
    }
  }, [])

  const actions = {
    toast,
    log,
    copyText,
    checkConnection,
    triggerLibraryScan,
    startScan,
    pollScanProgress,
    fetchReport,
    setFilter,
    setRowLimit,
    toggleGroup,
    toggleAllGroups,
    selectItem,
    toggleGroupSelect,
    setCheckedItems,
    onTargetInputChange,
    applyGroupTargetEdits,
    confirmSelected,
    confirmGroup,
    openConfirmModal,
    closeConfirmModal,
    runConfirm,
    pollConfirmProgress,
    deleteSourceItem,
    deleteSelectedSkipped,
  }

  return <AppStoreContext.Provider value={{ state, actions }}>{children}</AppStoreContext.Provider>
}

export function useAppStore() {
  const ctx = useContext(AppStoreContext)
  if (!ctx) throw new Error('useAppStore must be used within AppStoreProvider')
  return ctx
}
