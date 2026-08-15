import { createContext, useContext, useEffect, useReducer, useRef } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost, getAuthToken, setAuthToken } from '../api/apiClient.js'
import { computePathSync, defaultSelection, groupItems, isCrossDriveItem, mapReportItems } from '../utils/report.js'
import { buildTransferQueue, deriveTransferQueue, TRANSFER_DONE_REMOVE_MS } from '../utils/transfer.js'

const AppStoreContext = createContext(null)

const POLL_INTERVAL_MS = 2000
const LOG_LIMIT = 1000

function pageFromPath() {
  if (typeof window === 'undefined') return 'scan'
  const match = window.location.pathname.match(/^\/(scan|settings|apikeys)(?:\/|$)/)
  return match ? match[1] : 'scan'
}

function pathForPage(page) {
  return page === 'scan' ? '/' : '/' + page
}

const initialState = {
  connStatus: 'connecting',
  connMessage: 'connecting...',
  authRequired: false,
  authed: false,
  page: 'scan',
  jellyfinLibraries: [],
  libraryScanning: null,
  scanId: null,
  scanRunning: false,
  scanProgress: null,
  reportLoading: false,
  reportVisible: false,
  reportAll: [],
  reportSummary: null,
  currentItems: [],
  reportGroups: [],
  selectedIds: [],
  expandedGroups: [],
  confirmActive: false,
  confirmButtonLabel: 'Confirm Selected',
  confirmModal: { open: false, itemIds: [], label: '', progress: null },
  logEntries: [],
  logsVisible: false,
  toasts: [],
  transferQueue: [],
  transferSummary: null,
  adminEnv: null,
  adminEnvPending: [],
  adminKeys: [],
  adminLoading: false,
}

function toggleInList(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_CONN':
      return { ...state, connStatus: action.status, connMessage: action.message }
    case 'SET_AUTH':
      return { ...state, authRequired: action.authRequired, authed: action.authed }
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
    case 'SET_REPORT_LOADING':
      return { ...state, reportLoading: action.reportLoading }
    case 'SET_CONFIRM_ACTIVE':
      return { ...state, confirmActive: action.confirmActive }
    case 'SET_CONFIRM_BUTTON_LABEL':
      return { ...state, confirmButtonLabel: action.label }
    case 'SET_CONFIRM_MODAL':
      return { ...state, confirmModal: action.modal }
    case 'SET_REPORT':
      return { ...state, ...action.payload, reportLoading: false }
    case 'SET_SELECTION':
      return { ...state, selectedIds: action.selectedIds }
    case 'SET_ITEMS':
      return { ...state, currentItems: action.currentItems, reportGroups: action.reportGroups }
    case 'TOGGLE_GROUP':
      return { ...state, expandedGroups: toggleInList(state.expandedGroups, action.gid) }
    case 'SET_GROUPS_EXPANDED':
      return { ...state, expandedGroups: action.list }
    case 'ADD_LOG':
      return { ...state, logEntries: [...state.logEntries, action.entry].slice(-LOG_LIMIT) }
    case 'SET_LOGS_VISIBLE':
      return { ...state, logsVisible: action.visible }
    case 'ADD_TOAST':
      return { ...state, toasts: [...state.toasts, action.toast] }
    case 'REMOVE_TOAST':
      return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) }
    case 'SET_TRANSFER_QUEUE':
      return { ...state, transferQueue: action.queue }
    case 'SET_TRANSFER_SUMMARY':
      return { ...state, transferSummary: action.summary }
    case 'REMOVE_TRANSFER_ITEM':
      return { ...state, transferQueue: state.transferQueue.filter((t) => t.id !== action.id) }
    case 'SET_PAGE':
      return { ...state, page: action.page }
    case 'SET_ADMIN_ENV':
      return { ...state, adminEnv: action.env, adminEnvPending: action.env?.pending || [] }
    case 'SET_ADMIN_KEYS':
      return { ...state, adminKeys: action.keys || [] }
    case 'SET_ADMIN_LOADING':
      return { ...state, adminLoading: action.loading }
    default:
      return state
  }
}

let toastSeq = 0

export function AppStoreProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState, (base) => ({ ...base, page: pageFromPath() }))
  const stateRef = useRef(state)
  stateRef.current = state
  const timers = useRef({ scanPoll: null, confirmPoll: null, paste: null, transferRemoval: {} })
  const confirmStateRef = useRef({ completed: 0, failed: 0 })
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

  function toggleLogs() {
    dispatch({ type: 'SET_LOGS_VISIBLE', visible: !stateRef.current.logsVisible })
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
        toast('Copied: ' + text, 'good')
        return
      }
    } catch (e) {
      /* fall through to legacy fallback below */
    }
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.top = '0'
      ta.style.left = '0'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (!ok) throw new Error('copy command failed')
      toast('Copied: ' + text, 'good')
    } catch (e) {
      toast('Failed to copy', 'err')
    }
  }

  // ---- transfer queue (bottom-right copy progress toasts) ----
  function scheduleTransferRemovals(queue) {
    const now = Date.now()
    queue.forEach((t) => {
      if ((t.state !== 'done' && t.state !== 'failed') || !t.doneAt) return
      if (timers.current.transferRemoval[t.id]) return
      const delay = Math.max(0, TRANSFER_DONE_REMOVE_MS - (now - t.doneAt))
      timers.current.transferRemoval[t.id] = setTimeout(() => {
        delete timers.current.transferRemoval[t.id]
        dispatch({ type: 'REMOVE_TRANSFER_ITEM', id: t.id })
      }, delay)
    })
  }

  // ---- report rendering ----
  function renderReport(report) {
    const all = mapReportItems(report)
    const s = report.summary || {}
    const withLive = all.map((i) => ({ ...i, _liveTarget: i.targetPath }))
    const groups = groupItems(withLive)
    dispatch({
      type: 'SET_REPORT',
      payload: {
        reportVisible: true,
        reportAll: all,
        reportSummary: s,
        currentItems: withLive,
        reportGroups: groups,
        selectedIds: defaultSelection(withLive),
        expandedGroups: groups.map((g, gi) => 'group-' + gi),
        scanId: s.scan_id || stateRef.current.scanId,
      },
    })
  }

  async function fetchReport() {
    const scanId = stateRef.current.scanId
    if (!stateRef.current.reportVisible) {
      dispatch({ type: 'SET_REPORT_LOADING', reportLoading: true })
    }
    try {
      const result = await apiGet('/scans/current/report')
      if (!result || result.hint) {
        if (scanId) log(result?.hint || 'No scan report available', 'warn')
        dispatch({ type: 'SET_SCAN_ID', scanId: null })
        dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
        dispatch({ type: 'SET_REPORT', payload: { reportVisible: false } })
        return
      }
      if (result.progress) {
        dispatch({ type: 'SET_REPORT_LOADING', reportLoading: false })
        log('Scan is still running — check progress first', 'warn')
        return
      }
      dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
      if (result.summary?.scan_id) dispatch({ type: 'SET_SCAN_ID', scanId: result.summary.scan_id })
      renderReport(result)
      log('Report loaded — ' + (result.summary?.action_required || 0) + ' actions pending', 'good')
    } catch (e) {
      if (handleApiError(e)) return
      dispatch({ type: 'SET_REPORT_LOADING', reportLoading: false })
      log('Report error: ' + e.message, 'err')
      toast('Report error: ' + e.message, 'err')
    }
  }

  // ---- auth helpers ----
  function handleApiError(e) {
    if (e.status === 401) {
      setAuthToken('')
      dispatch({ type: 'SET_AUTH', authRequired: true, authed: false })
      dispatch({ type: 'SET_CONN', status: 'connected', message: 'login required' })
      toast('Session expired — please log in', 'warn')
      return true
    }
    return false
  }

  async function login(password) {
    try {
      const res = await apiPost('/login', { password })
      setAuthToken(res.token)
      dispatch({ type: 'SET_AUTH', authRequired: true, authed: true })
      dispatch({ type: 'SET_CONN', status: 'connected', message: 'connected' })
      toast(res.directLogin ? 'Logged in' : 'Login successful', 'good')
      try {
        await loadLibraries()
      } catch (e) {
        /* library load is best-effort; the panel still works */
      }
    } catch (e) {
      setAuthToken('')
      log('Login failed: ' + e.message, 'err')
      toast('Login failed: ' + e.message, 'err')
      throw e
    }
  }

  async function logout() {
    try {
      await apiPost('/logout', {})
    } catch (e) {
      /* token may already be invalid */
    }
    setAuthToken('')
    dispatch({ type: 'SET_AUTH', authRequired: true, authed: false })
  }

  async function loadLibraries() {
    const libs = await apiGet('/libraries')
    const libraries = libs.libraries || []
    dispatch({ type: 'SET_LIBRARIES', libraries })
    log('Loaded ' + libraries.length + ' libraries', 'good')
    fetchReport()
  }

  // ---- connection ----
  async function checkConnection() {
    try {
      const st = await apiGet('/status')
      const required = !!(st.auth?.required || st.auth_required)
      if (required && !getAuthToken()) {
        dispatch({ type: 'SET_AUTH', authRequired: true, authed: false })
        dispatch({ type: 'SET_CONN', status: 'connected', message: 'login required' })
        log('Login required to view the panel', 'warn')
        return
      }
      if (required) {
        // Token already stored (e.g. page reload) — validate it against a protected route.
        try {
          const libs = await apiGet('/libraries')
          dispatch({ type: 'SET_AUTH', authRequired: true, authed: true })
          dispatch({ type: 'SET_LIBRARIES', libraries: libs.libraries || [] })
          dispatch({ type: 'SET_CONN', status: 'connected', message: 'connected' })
          fetchReport()
          return
        } catch (e) {
          if (e.status === 401) {
            setAuthToken('')
            dispatch({ type: 'SET_AUTH', authRequired: true, authed: false })
            dispatch({ type: 'SET_CONN', status: 'connected', message: 'login required' })
            log('Login required to view the panel', 'warn')
            return
          }
          throw e
        }
      }
      dispatch({ type: 'SET_AUTH', authRequired: false, authed: true })
      dispatch({ type: 'SET_CONN', status: 'connected', message: 'connected' })
      log('Connected to the JellySort API', 'good')
      await loadLibraries()
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
      const result = await apiPost('/libraries/scan', { libraryName: name })
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
    dispatch({ type: 'SET_REPORT_LOADING', reportLoading: false })
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
      const result = await apiPost('/scans', {})
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
      const result = await apiGet('/scans/current/progress')
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
        dispatch({ type: 'SET_REPORT_LOADING', reportLoading: true })
        toast('Scan completed — loading report...', 'good')
        dispatch({ type: 'SET_SCAN_PROGRESS', progress: null })
        setTimeout(fetchReport, 500)
      } else if (result.status === 'running') {
        if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
        timers.current.scanPoll = setTimeout(pollScanProgress, POLL_INTERVAL_MS)
      }
    } catch (e) {
      log('Progress error: ' + e.message, 'err')
      if (stateRef.current.scanRunning) {
        if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
        timers.current.scanPoll = setTimeout(pollScanProgress, POLL_INTERVAL_MS)
      }
    }
  }

  // ---- report controls ----
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
      await apiPatch('/scans/current/items', {
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
      Object.values(timers.current.transferRemoval || {}).forEach(clearTimeout)
      timers.current.transferRemoval = {}
      confirmStateRef.current = { completed: 0, failed: 0 }
      const queue = buildTransferQueue(itemIds, stateRef.current.currentItems)
      dispatch({ type: 'SET_TRANSFER_QUEUE', queue })
      dispatch({
        type: 'SET_TRANSFER_SUMMARY',
        summary: { processed: 0, total: itemIds.length, status: 'running', counts: {} },
      })
      dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm running...' })
      dispatch({ type: 'SET_CONFIRM_MODAL', modal: { open: false, itemIds: [], label: '', progress: null } })
      log('Confirming ' + itemIds.length + ' item(s)...', 'info')
      const result = await apiPost('/scans/current/confirm', {
        scanId: stateRef.current.scanId,
        itemIds,
      })
      log('Confirm started! ID: ' + stateRef.current.scanId, 'good')
      toast('Confirm started in background', 'good')
      pollConfirmProgress()
    } catch (e) {
      log('Confirm error: ' + e.message, 'err')
      toast('Confirm error: ' + e.message, 'err')
      dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
      dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
      dispatch({ type: 'SET_TRANSFER_QUEUE', queue: [] })
      dispatch({ type: 'SET_TRANSFER_SUMMARY', summary: null })
      closeConfirmModal()
    }
  }

  async function pollConfirmProgress() {
    if (!stateRef.current.confirmActive) return
    try {
      const result = await apiGet('/scans/current/confirm-progress')
      const p = result.processed ?? 0
      const t = result.total ?? 0
      log('Confirm progress: ' + p + '/' + t + ' (' + (result.status || 'unknown') + ')', 'info')
      const derived = deriveTransferQueue(stateRef.current.transferQueue, result, confirmStateRef.current)
      confirmStateRef.current = derived.state
      dispatch({ type: 'SET_TRANSFER_QUEUE', queue: derived.queue })
      dispatch({
        type: 'SET_TRANSFER_SUMMARY',
        summary: {
          processed: result.processed ?? 0,
          total: result.total ?? 0,
          status: result.status,
          counts: result.counts || {},
        },
      })
      scheduleTransferRemovals(derived.queue)

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
      'Delete the source file permanently?\n\n' +
        source +
        '\n\nThe file will be removed and skipped from the move plan. This cannot be undone.'
    )
    if (!ok) return
    try {
      await apiDelete('/scans/current/items', {
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
      await apiDelete('/scans/current/items', {
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

  // ---- admin: page navigation ----
  function setPage(page) {
    if (page !== 'scan' && page !== 'settings' && page !== 'apikeys') page = 'scan'
    const target = pathForPage(page)
    if (window.location.pathname !== target) window.history.pushState({}, '', target)
    dispatch({ type: 'SET_PAGE', page })
    if (page === 'settings' && !stateRef.current.adminEnv) loadEnv()
    if (page === 'apikeys' && !stateRef.current.adminKeys.length && !stateRef.current.adminLoading) loadApiKeys()
  }

  // ---- admin: environment settings ----
  async function loadEnv() {
    dispatch({ type: 'SET_ADMIN_LOADING', loading: true })
    try {
      const env = await apiGet('/admin/env')
      dispatch({ type: 'SET_ADMIN_ENV', env })
    } catch (e) {
      if (handleApiError(e)) return
      log('Failed to load settings: ' + e.message, 'err')
      toast('Failed to load settings: ' + e.message, 'err')
    } finally {
      dispatch({ type: 'SET_ADMIN_LOADING', loading: false })
    }
  }

  async function saveEnv(updates) {
    dispatch({ type: 'SET_ADMIN_LOADING', loading: true })
    try {
      const result = await apiPost('/admin/env', { updates })
      await loadEnv()
      return result
    } catch (e) {
      if (handleApiError(e)) return
      log('Failed to save settings: ' + e.message, 'err')
      toast('Failed to save settings: ' + e.message, 'err')
      throw e
    } finally {
      dispatch({ type: 'SET_ADMIN_LOADING', loading: false })
    }
  }

  // ---- admin: API keys ----
  async function loadApiKeys() {
    dispatch({ type: 'SET_ADMIN_LOADING', loading: true })
    try {
      const res = await apiGet('/admin/api-keys')
      dispatch({ type: 'SET_ADMIN_KEYS', keys: res.keys || [] })
    } catch (e) {
      if (handleApiError(e)) return
      log('Failed to load API keys: ' + e.message, 'err')
      toast('Failed to load API keys: ' + e.message, 'err')
    } finally {
      dispatch({ type: 'SET_ADMIN_LOADING', loading: false })
    }
  }

  async function createApiKey(payload) {
    dispatch({ type: 'SET_ADMIN_LOADING', loading: true })
    try {
      const result = await apiPost('/admin/api-keys', payload)
      await loadApiKeys()
      return result
    } catch (e) {
      if (handleApiError(e)) return
      log('Failed to create API key: ' + e.message, 'err')
      toast('Failed to create API key: ' + e.message, 'err')
      throw e
    } finally {
      dispatch({ type: 'SET_ADMIN_LOADING', loading: false })
    }
  }

  async function toggleApiKey(id, enabled) {
    try {
      await apiPatch('/admin/api-keys/' + id, { enabled })
      await loadApiKeys()
    } catch (e) {
      if (handleApiError(e)) return
      log('Failed to update API key: ' + e.message, 'err')
      toast('Failed to update API key: ' + e.message, 'err')
    }
  }

  async function deleteApiKey(id) {
    try {
      await apiDelete('/admin/api-keys/' + id)
      dispatch({ type: 'SET_ADMIN_KEYS', keys: stateRef.current.adminKeys.filter((k) => k.id !== id) })
      toast('API key deleted', 'good')
    } catch (e) {
      if (handleApiError(e)) return
      log('Failed to delete API key: ' + e.message, 'err')
      toast('Failed to delete API key: ' + e.message, 'err')
    }
  }

  useEffect(() => {
    const onPopState = () => {
      const page = pageFromPath()
      if (page !== stateRef.current.page) dispatch({ type: 'SET_PAGE', page })
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    if (!state.authed) return
    if (state.page === 'settings' && !stateRef.current.adminEnv) loadEnv()
    if (state.page === 'apikeys' && !stateRef.current.adminKeys.length && !stateRef.current.adminLoading) loadApiKeys()
  }, [state.authed, state.page])

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    checkConnection()
    return () => {
      if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
      if (timers.current.confirmPoll) clearTimeout(timers.current.confirmPoll)
      Object.values(timers.current.transferRemoval || {}).forEach(clearTimeout)
    }
  }, [])

  const actions = {
    toast,
    log,
    toggleLogs,
    copyText,
    checkConnection,
    login,
    logout,
    loadLibraries,
    triggerLibraryScan,
    startScan,
    pollScanProgress,
    fetchReport,
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
    setPage,
    loadEnv,
    saveEnv,
    loadApiKeys,
    createApiKey,
    toggleApiKey,
    deleteApiKey,
  }

  return <AppStoreContext.Provider value={{ state, actions }}>{children}</AppStoreContext.Provider>
}

export function useAppStore() {
  const ctx = useContext(AppStoreContext)
  if (!ctx) throw new Error('useAppStore must be used within AppStoreProvider')
  return ctx
}
