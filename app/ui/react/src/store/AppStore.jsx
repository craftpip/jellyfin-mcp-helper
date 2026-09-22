import { createContext, useContext, useEffect, useReducer, useRef, useCallback } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost, getAuthToken, setAuthToken } from '../api/apiClient.js'
import { computePathSync, defaultSelection, groupItems, isCrossDriveItem, mapReportItems } from '../utils/report.js'
import { isCrossDrive } from '../utils/format.js'
import { buildTransferQueue, buildTransferQueueFromGroups, deriveTransferQueue, TRANSFER_DONE_REMOVE_MS } from '../utils/transfer.js'
import { usePoll } from '../hooks/usePoll.js'
import { confirmDialog } from '../components/ConfirmDialog.jsx'
import { reportInitialState, reportReducer, toggleInList } from './slices/reportSlice.js'
import { scanInitialState, scanReducer } from './slices/scanSlice.js'
import { adminInitialState, adminReducer } from './slices/adminSlice.js'

const AppStoreContext = createContext(null)

const TRANSFER_ACTIVE_KEY = 'jsort_transfer_active'
const TRANSFER_MINIMIZED_KEY = 'jsort_transfer_minimized'
const TRANSFER_SNAPSHOT_KEY = 'jsort_transfer_snapshot'

function getInitialTransferMinimized() {
  if (typeof window !== 'undefined') {
    try {
      return localStorage.getItem(TRANSFER_MINIMIZED_KEY) === '1'
    } catch {}
  }
  return false
}

function readTransferSnapshot() {
  if (typeof window === 'undefined') return null
  try {
    const raw = localStorage.getItem(TRANSFER_SNAPSHOT_KEY)
    if (!raw) return null
    const snap = JSON.parse(raw)
    if (!snap || !Array.isArray(snap.queue)) return null
    // A summary-only snapshot (rows faded) still restores the header/strip.
    if (!snap.queue.length && !snap.summary) return null
    return snap
  } catch {
    return null
  }
}

// Rows restored from a snapshot: a mid-copy row goes back to queued (its live
// progress is gone), and done rows get a fresh doneAt so they fade after the
// usual delay instead of vanishing instantly on stale timestamps.
function sanitizeRestoredQueue(queue, now = Date.now()) {
  return queue.map((t) =>
    t.state === 'copying'
      ? { ...t, state: 'queued', progress: null }
      : t.state === 'done'
        ? { ...t, doneAt: now }
        : t
  )
}

const POLL_INTERVAL_MS = 2000
const LOG_LIMIT = 1000

function pageFromPath() {
  if (typeof window === 'undefined') return 'scan'
  const match = window.location.pathname.match(/^\/(scan|settings|history)(?:\/|$)/)
  return match ? match[1] : 'scan'
}

function pathForPage(page) {
  return page === 'scan' ? '/' : '/' + page
}

function getInitialFilter() {
  if (typeof window !== 'undefined') {
    try {
      const url = new URL(window.location.href)
      const f = url.searchParams.get('filter')
      if (f && ['all', 'move', 'replace', 'extra', 'suspect'].includes(f)) return f
    } catch {}
    try {
      const s = localStorage.getItem('jsort_filter')
      if (s && ['all', 'move', 'replace', 'extra', 'suspect'].includes(s)) return s
    } catch {}
  }
  return 'all'
}

function getInitialQuery() {
  if (typeof window !== 'undefined') {
    try {
      const url = new URL(window.location.href)
      const q = url.searchParams.get('q')
      if (q !== null) return q
    } catch {}
    try {
      const s = localStorage.getItem('jsort_query')
      if (s) return s
    } catch {}
  }
  return ''
}

const initialState = {
  // Connection & auth
  connStatus: 'connecting',
  connMessage: 'connecting...',
  authRequired: false,
  authed: false,
  rootsConfigured: true,
  page: 'scan',
  navMenuOpen: false,
  jellyfinLibraries: [],
  libraryScanning: null,
  // Scan slice
  ...scanInitialState,
  // Report slice
  reportLoading: false,
  reportVisible: false,
  reportAll: [],
  reportSummary: null,
  currentItems: [],
  reportGroups: [],
  selectedIds: [],
  expandedGroups: [],
  currentFilter: getInitialFilter(),
  searchQuery: getInitialQuery(),
  reportServiceErrors: null,
  undoTick: 0,
  // Confirm & transfer
  confirmActive: false,
  confirmButtonLabel: 'Confirm Selected',
  confirmModal: { open: false, itemIds: [], label: '', progress: null },
  logEntries: [],
  logsVisible: false,
  toasts: [],
  transferQueue: [],
  transferSummary: null,
  transferMinimized: getInitialTransferMinimized(),
  browseModal: null,
  // Admin slice
  ...adminInitialState,
}

const REPORT_TYPES = new Set(['SET_REPORT', 'SET_SELECTION', 'SET_ITEMS', 'TOGGLE_GROUP', 'SET_GROUPS_EXPANDED', 'SET_FILTER', 'SET_SEARCH_QUERY'])
const SCAN_TYPES = new Set(['SET_SCAN_ID', 'SET_SCAN_RUNNING', 'SET_SCAN_PROGRESS'])
const ADMIN_TYPES = new Set(['SET_ADMIN_ENV', 'SET_ADMIN_LOADING'])

function reducer(state, action) {
  if (REPORT_TYPES.has(action.type)) return reportReducer(state, action)
  if (SCAN_TYPES.has(action.type)) return scanReducer(state, action)
  if (ADMIN_TYPES.has(action.type)) return adminReducer(state, action)
  switch (action.type) {
    case 'SET_CONN':
      return { ...state, connStatus: action.status, connMessage: action.message }
    case 'SET_AUTH':
      return { ...state, authRequired: action.authRequired, authed: action.authed }
    case 'SET_ROOTS_CONFIGURED':
      return { ...state, rootsConfigured: action.rootsConfigured }
    case 'SET_UNDO_TICK':
      return { ...state, undoTick: state.undoTick + 1 }
    case 'SET_LIBRARIES':
      return { ...state, jellyfinLibraries: action.libraries }
    case 'SET_LIBRARY_SCANNING':
      return { ...state, libraryScanning: action.name }
    case 'SET_REPORT_LOADING':
      return { ...state, reportLoading: action.reportLoading }
    case 'SET_CONFIRM_ACTIVE':
      return { ...state, confirmActive: action.confirmActive }
    case 'SET_CONFIRM_BUTTON_LABEL':
      return { ...state, confirmButtonLabel: action.label }
    case 'SET_CONFIRM_MODAL':
      return { ...state, confirmModal: action.modal }
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
    case 'SET_TRANSFER_MINIMIZED':
      return { ...state, transferMinimized: action.minimized }
    case 'REMOVE_TRANSFER_ITEM':
      return { ...state, transferQueue: state.transferQueue.filter((t) => t.id !== action.id) }
    case 'SET_BROWSE':
      return { ...state, browseModal: action.browse }
    case 'SET_PAGE':
      return { ...state, page: action.page }
    case 'SET_NAV_MENU':
      return { ...state, navMenuOpen: action.open }
    default:
      return state
  }
}

let toastSeq = 0

export function AppStoreProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState, (base) => {
    // Seed a persisted transfer panel (minimized strip included) so a
    // refresh brings back the same panel before any effect can clear it.
    try {
      const snap = readTransferSnapshot()
      if (snap) {
        return {
          ...base,
          page: pageFromPath(),
          transferQueue: sanitizeRestoredQueue(snap.queue),
          transferSummary: snap.summary || null,
          transferMinimized: typeof snap.minimized === 'boolean' ? snap.minimized : base.transferMinimized,
        }
      }
    } catch {}
    return { ...base, page: pageFromPath() }
  })
  const stateRef = useRef(state)
  stateRef.current = state
  const timers = useRef({ scanPoll: null, confirmPoll: null, paste: null, transferRemoval: {}, search: null })
  const confirmStateRef = useRef({ completed: 0, failed: 0 })
  const confirmActiveRef = useRef(false)
  const pendingBatchesRef = useRef([])
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
      if (t.state !== 'done' || !t.doneAt) return
      if (timers.current.transferRemoval[t.id]) return
      const delay = Math.max(0, TRANSFER_DONE_REMOVE_MS - (now - t.doneAt))
      timers.current.transferRemoval[t.id] = setTimeout(() => {
        delete timers.current.transferRemoval[t.id]
        const stillThere = stateRef.current.transferQueue.find((x) => x.id === t.id)
        if (!stillThere || stillThere.state !== 'done') return
        dispatch({ type: 'REMOVE_TRANSFER_ITEM', id: t.id })
      }, delay)
    })
  }

  function setTransferMinimized(minimized) {
    try {
      localStorage.setItem(TRANSFER_MINIMIZED_KEY, minimized ? '1' : '0')
    } catch {}
    dispatch({ type: 'SET_TRANSFER_MINIMIZED', minimized: !!minimized })
  }

  function dismissTransfer() {
    closeConfirmStream()
    confirmActiveRef.current = false
    Object.values(timers.current.transferRemoval || {}).forEach(clearTimeout)
    timers.current.transferRemoval = {}
    confirmStateRef.current = { completed: 0, failed: 0 }
    dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
    dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
    dispatch({ type: 'SET_TRANSFER_QUEUE', queue: [] })
    dispatch({ type: 'SET_TRANSFER_SUMMARY', summary: null })
    try {
      localStorage.removeItem(TRANSFER_ACTIVE_KEY)
      localStorage.removeItem(TRANSFER_SNAPSHOT_KEY)
    } catch {}
    fetchReport()
  }

  // Restore a still-active transfer panel after a page reload. Gated behind
  // the transfer-active flag set by runConfirm, so unrelated page loads never
  // poll confirm progress. The backend queue_groups payload is the source of
  // truth for per-file rows.
  async function restoreTransfer() {
    let active = false
    try {
      active = localStorage.getItem(TRANSFER_ACTIVE_KEY) === '1'
    } catch {}
    if (!active || confirmActiveRef.current) return
    let result
    try {
      result = await apiGet('/scans/current/confirm-progress')
    } catch {
      return
    }
    const status = result && result.status
    const total = (result && result.total) || 0
    if ((status !== 'running' && status !== 'completed' && status !== 'failed') || (!total && !(result.queue_length > 0))) {
      try {
        localStorage.removeItem(TRANSFER_ACTIVE_KEY)
      } catch {}
      return
    }
    const queue = result.queue_groups && result.queue_groups.length
      ? buildTransferQueueFromGroups(result.queue_groups)
      : stateRef.current.transferQueue
    confirmStateRef.current = { completed: 0, failed: 0 }
    const derived = deriveTransferQueue(queue, result, confirmStateRef.current)
    confirmStateRef.current = derived.state
    const running = status === 'running'
    confirmActiveRef.current = running
    dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: running })
    dispatch({ type: 'SET_TRANSFER_QUEUE', queue: derived.queue })
    dispatch({
      type: 'SET_TRANSFER_SUMMARY',
      summary: {
        processed: result.processed ?? 0,
        total: total + (result.queue_items || 0),
        status,
        counts: result.counts || {},
        queueLength: result.queue_length || 0,
        queueItems: result.queue_items || 0,
      },
    })
    dispatch({ type: 'SET_TRANSFER_MINIMIZED', minimized: getInitialTransferMinimized() })
    log('Transfer progress restored after reload (' + status + ')', 'info')
    if (running) {
      dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm running...' })
      subscribeConfirmProgress()
    }
    scheduleTransferRemovals(derived.queue)
  }

  // ---- report rendering ----
  function renderReport(report) {
    const all = mapReportItems(report)
    const s = report.summary || {}
    const withLive = all.map((i) => ({ ...i, _liveTarget: i.targetPath, _linked: true }))
    const groups = groupItems(withLive)
    dispatch({
      type: 'SET_REPORT',
      payload: {
        reportVisible: true,
        reportAll: all,
        reportSummary: s,
        reportServiceErrors: report.service_errors || null,
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
        log('Scan is still running — showing live progress', 'info')
        dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: true })
        dispatch({ type: 'SET_SCAN_PROGRESS', progress: result.progress })
        if (result.progress.scan_id) dispatch({ type: 'SET_SCAN_ID', scanId: result.progress.scan_id })
        if (result.summary?.scan_id) dispatch({ type: 'SET_SCAN_ID', scanId: result.summary.scan_id })
        subscribeScanProgress()
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

  async function undoScan(scanId = 'current') {
    try {
      const result = await apiPost(`/scans/${scanId}/undo`)
      if (!result?.ok) throw new Error(result?.error || 'undo failed')
      const restored = result.restored_count || 0
      const skipped = (result.skipped || []).length
      if (restored > 0) {
        toast(`Undone: ${restored} file${restored === 1 ? '' : 's'} moved back to downloads` + (skipped ? ` · ${skipped} skipped` : ''), 'good')
        log(`Undo complete — ${restored} restored, ${skipped} skipped`, 'good')
      } else {
        toast('Nothing to undo — no restorable moves found', 'warn')
      }
      dispatch({ type: 'SET_UNDO_TICK' })
      fetchReport()
      return { ...result, error: null }
    } catch (e) {
      if (handleApiError(e)) return null
      const msg = e.status === 404 ? 'No scan found to undo' : 'Undo failed: ' + e.message
      toast(msg, 'err')
      log(msg, 'err')
      return null
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
    closeScanStream()
    closeConfirmStream()
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

  // ---- setup wizard ----
  function dismissSetup() {
    dispatch({ type: 'SET_ROOTS_CONFIGURED', rootsConfigured: true })
    toast('Setup skipped — configure paths later in Settings', 'info')
  }

  // ---- connection ----
  async function checkConnection() {
    try {
      const st = await apiGet('/status')
      const required = !!(st.auth?.required || st.auth_required)
      dispatch({ type: 'SET_ROOTS_CONFIGURED', rootsConfigured: st.roots_configured !== false })
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
          restoreTransfer()
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
      restoreTransfer()
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
  async function startScan(opts = {}) {
    const fullRescan = !!opts.fullRescan
    if (fullRescan) {
      const ok = await confirmDialog({
        title: 'Full rescan',
        message:
          'Rescan all will overwrite the current report and discard any edits (retargets). New files will still be found with a normal Scan. Continue with full rescan?',
        confirmLabel: 'Full Rescan',
      })
      if (!ok) return
    }
    if (stateRef.current.scanRunning || stateRef.current.confirmActive) return
    dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: true })
    dispatch({ type: 'SET_REPORT_LOADING', reportLoading: false })
    log(fullRescan ? 'Starting full rescan (overwrite)...' : 'Starting scan...', 'info')
    if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
    dispatch({
      type: 'SET_SCAN_PROGRESS',
      progress: {
        percent: 0,
        status: 'starting',
        lines: [fullRescan ? 'Starting full rescan...' : 'Starting scan...', 'Waiting for backend to create the scan plan'],
      },
    })
    try {
      const result = await apiPost('/scans', fullRescan ? { fullRescan: true } : {})
      const scanId = result.scan_id || null
      dispatch({ type: 'SET_SCAN_ID', scanId })
      log('Scan started! ID: ' + scanId + ' — ' + (result.message || ''), 'good')
      toast('Scan started', 'good')
      log(
        'Progress: ' + result.processed + '/' + result.total + ' (' + (result.percent || 0) + '%)',
        'info'
      )
      dispatch({ type: 'SET_SCAN_PROGRESS', progress: result })
      subscribeScanProgress()
    } catch (e) {
      log('Scan error: ' + e.message, 'err')
      toast('Scan error: ' + e.message, 'err')
      dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
    }
  }

  function handleScanProgress(result) {
    if (!result || result.hint) {
      log(result?.hint || 'No active scan found', 'warn')
      dispatch({ type: 'SET_SCAN_PROGRESS', progress: null })
      dispatch({ type: 'SET_SCAN_ID', scanId: null })
      dispatch({ type: 'SET_SCAN_RUNNING', scanRunning: false })
      return true
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
      return true
    }
    return false
  }

  function closeScanStream() {
    if (timers.current.scanEs) {
      try { timers.current.scanEs.close() } catch { /* already closed */ }
      timers.current.scanEs = null
    }
  }

  function subscribeScanProgress() {
    closeScanStream()
    // EventSource is unavailable in some environments — fall back to polling.
    if (typeof EventSource === 'undefined') {
      timers.current.scanPoll = setTimeout(pollScanProgress, 0)
      return
    }
    const es = new EventSource('/api/scans/progress/events?token=' + encodeURIComponent(getAuthToken()))
    timers.current.scanEs = es
    es.onmessage = (ev) => {
      let data
      try { data = JSON.parse(ev.data) } catch { return }
      const done = handleScanProgress(data)
      if (done) closeScanStream()
    }
    es.onerror = () => {
      closeScanStream()
      if (stateRef.current.scanRunning && !timers.current.scanPoll) {
        log('Live progress unavailable — falling back to polling', 'warn')
        timers.current.scanPoll = setTimeout(pollScanProgress, 0)
      }
    }
  }

  async function pollScanProgress() {
    try {
      const result = await apiGet('/scans/current/progress')
      const done = handleScanProgress(result)
      if (!done && stateRef.current.scanRunning) {
        if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
        timers.current.scanPoll = setTimeout(pollScanProgress, POLL_INTERVAL_MS)
      } else if (!done && !stateRef.current.scanRunning) {
        // Terminal-but-not-completed statuses (e.g. failed): stop silently,
        // matching the pre-SSE behaviour.
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

  function toggleLink(idx) {
    const items = stateRef.current.currentItems
    const item = items[idx]
    if (!item) return
    const updated = [...items]
    updated[idx] = { ...item, _linked: item._linked === false ? true : false }
    dispatch({ type: 'SET_ITEMS', currentItems: updated, reportGroups: groupItems(updated) })
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
          const cross = isCrossDrive(item.sourcePath, u.targetPath)
          const applied = { ...item, targetPath: u.targetPath, originalTarget: u.targetPath, _liveTarget: u.targetPath, crossDrive: cross, originalCrossDrive: cross }
          return applied
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
    openConfirmModal(ids, '"' + group.title + '"')
  }

  async function runConfirm(itemIds) {
    log('Confirming ' + itemIds.length + ' item(s)...', 'info')
    try {
      const result = await apiPost('/scans/current/confirm', {
        scanId: stateRef.current.scanId,
        itemIds,
      })
      try {
        localStorage.setItem(TRANSFER_ACTIVE_KEY, '1')
      } catch {}
      setTransferMinimized(false)
      const queued = (result.queue_length || 0) > 0
      if (queued) {
        // A move is running on the backend: this batch is queued and will start
        // automatically when the current move finishes. Keep the running batch's
        // transfer queue intact; pollConfirmProgress rebuilds it for this batch
        // once the backend actually starts it.
        pendingBatchesRef.current.push({ itemIds })
        confirmActiveRef.current = true
        dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: true })
        dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm running...' })
        dispatch({ type: 'SET_CONFIRM_MODAL', modal: { open: false, itemIds: [], label: '', progress: null } })
        log('Confirm queued — ' + itemIds.length + ' item(s) behind the current move', 'info')
        toast('Added to queue — will start after the current move finishes', 'good')
        if (timers.current.confirmPoll) clearTimeout(timers.current.confirmPoll)
        subscribeConfirmProgress()
        return
      }
      confirmActiveRef.current = true
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
      log('Confirm started! ID: ' + stateRef.current.scanId, 'good')
      toast('Confirm started in background', 'good')
      subscribeConfirmProgress()
    } catch (e) {
      log('Confirm error: ' + e.message, 'err')
      toast('Confirm error: ' + e.message, 'err')
      confirmActiveRef.current = false
      dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
      dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
      dispatch({ type: 'SET_TRANSFER_QUEUE', queue: [] })
      dispatch({ type: 'SET_TRANSFER_SUMMARY', summary: null })
      closeConfirmModal()
    }
  }

  function applyConfirmProgress(result) {
    const p = result.processed ?? 0
    const t = result.total ?? 0
    const queueLength = result.queue_length || 0
    log(
      'Confirm progress: ' + p + '/' + t + ' (' + (result.status || 'unknown') + ')' +
        (queueLength > 0 ? ' · ' + queueLength + ' queued' : ''),
      'info'
    )

    if (result.status === 'running' && p < confirmStateRef.current.completed) {
      // A queued confirm batch just started: the backend reset the per-batch
      // counters, so this tab must swap its transfer queue to the new batch.
      log('Queued confirm batch started — ' + queueLength + ' still behind', 'info')
      const next = pendingBatchesRef.current.shift()
      if (next) {
        const queue = buildTransferQueue(next.itemIds, stateRef.current.currentItems)
        dispatch({ type: 'SET_TRANSFER_QUEUE', queue })
      }
      confirmStateRef.current = { completed: 0, failed: 0 }
      toast('Queued move started', 'good')
    }

    // The backend queue_groups payload is the source of truth for per-file
    // rows: rebuild grouped sections from it, keeping locally-done rows the
    // payload doesn't know about yet. Falls back to order-aligned derivation
    // when the payload is absent.
    const groups = Array.isArray(result.queue_groups) && result.queue_groups.length ? result.queue_groups : null
    let queue = stateRef.current.transferQueue
    if (groups) {
      const rebuilt = buildTransferQueueFromGroups(groups)
      const rebuiltIds = new Set(rebuilt.map((x) => x.id))
      const keepDone = queue.filter((x) => x.state === 'done' && !rebuiltIds.has(x.id))
      queue = rebuilt.concat(keepDone)
      if (result.status === 'running' && result.current_file) {
        queue = queue.map((x) =>
          x.sourcePath === result.current_file
            ? {
                ...x,
                state: 'copying',
                progress: {
                  percent: result.current_percent,
                  speed: result.current_speed,
                  speed_bytes: result.current_speed_bytes,
                  eta: result.current_eta,
                  copied: result.current_copied_bytes,
                  size: result.current_size_bytes,
                },
              }
            : x
        )
      }
      confirmStateRef.current = {
        completed: Math.max(confirmStateRef.current.completed, p),
        failed: result.counts?.failed ?? 0,
      }
    } else if (queue.length) {
      const derived = deriveTransferQueue(queue, result, confirmStateRef.current)
      confirmStateRef.current = derived.state
      queue = derived.queue
    }
    dispatch({ type: 'SET_TRANSFER_QUEUE', queue })
    const panelTotal = t + (result.queue_items || 0)
    dispatch({
      type: 'SET_TRANSFER_SUMMARY',
      summary: {
        processed: p,
        total: panelTotal,
        status: result.status,
        counts: result.counts || {},
        queueLength,
        queueItems: result.queue_items || 0,
      },
    })
    scheduleTransferRemovals(queue)

    if (result.status === 'completed' || result.status === 'idle') {
      if (queueLength === 0) {
        closeConfirmStream()
        Object.values(timers.current.transferRemoval || {}).forEach(clearTimeout)
        timers.current.transferRemoval = {}
        confirmActiveRef.current = false
        dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
        dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
        const moved = result.counts?.moved || 0
        const replaced = result.counts?.replaced || 0
        const failed = result.counts?.failed || 0
        log('Confirm completed. Moved: ' + moved + ', Replaced: ' + replaced + ', Failed: ' + failed, 'good')
        toast('Confirm completed! Moved: ' + moved + ', Replaced: ' + replaced + ', Failed: ' + failed, 'good')
        try {
          localStorage.removeItem(TRANSFER_ACTIVE_KEY)
        } catch {}
        setTimeout(fetchReport, 800)
        return true
      }
      // Defensive: a queued batch remains and the backend starts it right after
      // marking this one complete, so keep confirmActive and keep listening.
    }
    if (result.status === 'failed') {
      if (queueLength === 0) {
        closeConfirmStream()
        Object.values(timers.current.transferRemoval || {}).forEach(clearTimeout)
        timers.current.transferRemoval = {}
        confirmActiveRef.current = false
        dispatch({ type: 'SET_CONFIRM_ACTIVE', confirmActive: false })
        dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label: 'Confirm Selected' })
        try {
          localStorage.removeItem(TRANSFER_ACTIVE_KEY)
        } catch {}
        return true
      }
      // Defensive: queued batches remain and the backend starts the next one
      // right after the failure, so keep confirmActive and keep listening.
    }
    if (result.status === 'running') {
      const label = 'Moving ' + p + '/' + panelTotal + '...' + (queueLength > 0 ? ' · ' + queueLength + ' queued' : '')
      dispatch({ type: 'SET_CONFIRM_BUTTON_LABEL', label })
    }
    return false
  }

  function closeConfirmStream() {
    if (timers.current.confirmEs) {
      try { timers.current.confirmEs.close() } catch { /* already closed */ }
      timers.current.confirmEs = null
    }
  }

  function subscribeConfirmProgress() {
    if (!confirmActiveRef.current) return
    closeConfirmStream()
    // EventSource is unavailable in some environments — fall back to polling.
    if (typeof EventSource === 'undefined') {
      if (!timers.current.confirmPoll) timers.current.confirmPoll = setTimeout(pollConfirmProgress, 0)
      return
    }
    const es = new EventSource('/api/scans/confirm/events?token=' + encodeURIComponent(getAuthToken()))
    timers.current.confirmEs = es
    es.onmessage = (ev) => {
      let data
      try { data = JSON.parse(ev.data) } catch { return }
      applyConfirmProgress(data)
    }
    es.onerror = () => {
      closeConfirmStream()
      if (confirmActiveRef.current && !timers.current.confirmPoll) {
        log('Live progress stream lost — falling back to polling', 'warn')
        timers.current.confirmPoll = setTimeout(pollConfirmProgress, 0)
      }
    }
  }

  async function pollConfirmProgress() {
    if (!confirmActiveRef.current) return
    try {
      const result = await apiGet('/scans/current/confirm-progress')
      const done = applyConfirmProgress(result)
      if (done) return
    } catch (e) {
      log('Confirm progress error: ' + e.message, 'err')
    }
    if (confirmActiveRef.current) {
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
    const ok = await confirmDialog({
      title: 'Delete source file?',
      message: 'The file will be removed and skipped from the move plan. This cannot be undone.',
      detail: source,
      confirmLabel: 'Delete',
      danger: true,
    })
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
    const ok = await confirmDialog({
      title: 'Delete source files?',
      message: `Delete ${ids.length} source file(s) permanently? This cannot be undone.`,
      confirmLabel: 'Delete',
      danger: true,
    })
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

  // ---- browse + retarget (smart correction) ----
  function openBrowse(confirmId) {
    dispatch({ type: 'SET_BROWSE', browse: { open: true, confirmId } })
  }

  function closeBrowse() {
    dispatch({ type: 'SET_BROWSE', browse: null })
  }

  async function retargetItem(confirmId, directory, applyToGroup = false, reclassifyAsMovie = false) {
    if (stateRef.current.confirmActive) {
      toast('Wait for the current move to finish first', 'info')
      return
    }
    const item = stateRef.current.currentItems.find((i) => i.confirmId === confirmId)
    if (!item) return
    try {
      await apiPost('/scans/current/items/retarget', {
        scanId: stateRef.current.scanId,
        confirmId,
        directory,
        applyToGroup,
        reclassifyAsMovie,
      })
      const label = item.title || 'item'
      log(
        'Retargeted "' + label + '" to ' + directory +
          (applyToGroup ? ' (group)' : '') + (reclassifyAsMovie ? ' as movie' : ''),
        'good'
      )
      toast('Target updated for "' + label + '"', 'good')
      fetchReport()
    } catch (e) {
      log('Retarget error: ' + e.message, 'err')
      toast('Retarget error: ' + e.message, 'err')
    }
  }

  // ---- admin: page navigation ----
  function setPage(page) {
    if (page !== 'scan' && page !== 'settings' && page !== 'history') page = 'scan'
    const target = pathForPage(page)
    if (window.location.pathname !== target) window.history.pushState({}, '', target)
    dispatch({ type: 'SET_PAGE', page })
    if (page === 'settings' && !stateRef.current.adminEnv) loadEnv()
  }

  function setNavMenu(open) {
    dispatch({ type: 'SET_NAV_MENU', open: !!open })
  }

  function setFilter(filter) {
    const valid = ['all', 'move', 'replace', 'extra', 'suspect'].includes(filter) ? filter : 'all'
    dispatch({ type: 'SET_FILTER', filter: valid })
    try {
      localStorage.setItem('jsort_filter', valid)
      const url = new URL(window.location.href)
      if (valid === 'all') url.searchParams.delete('filter')
      else url.searchParams.set('filter', valid)
      window.history.replaceState({}, '', url.pathname + url.search + url.hash)
    } catch {}
  }

  function setSearchQuery(query) {
    dispatch({ type: 'SET_SEARCH_QUERY', query })
    if (timers.current.search) clearTimeout(timers.current.search)
    timers.current.search = setTimeout(() => {
      try {
        localStorage.setItem('jsort_query', query)
        const url = new URL(window.location.href)
        if (!query) url.searchParams.delete('q')
        else url.searchParams.set('q', query)
        window.history.replaceState({}, '', url.pathname + url.search + url.hash)
      } catch {}
    }, 200)
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

  async function saveEnv(updates, oldPasswords) {
    dispatch({ type: 'SET_ADMIN_LOADING', loading: true })
    try {
      const payload = oldPasswords && Object.keys(oldPasswords).length ? { updates, oldPasswords } : { updates }
      const result = await apiPost('/admin/env', payload)
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

  useEffect(() => {
    const onPopState = () => {
      const page = pageFromPath()
      if (page !== stateRef.current.page) dispatch({ type: 'SET_PAGE', page })
      try {
        const url = new URL(window.location.href)
        const f = url.searchParams.get('filter')
        const q = url.searchParams.get('q')
        if (f && ['all', 'move', 'replace', 'extra', 'suspect'].includes(f) && f !== stateRef.current.currentFilter) {
          dispatch({ type: 'SET_FILTER', filter: f })
        } else if (!f && stateRef.current.currentFilter !== 'all') {
          dispatch({ type: 'SET_FILTER', filter: 'all' })
        }
        if (q !== null && q !== stateRef.current.searchQuery) {
          dispatch({ type: 'SET_SEARCH_QUERY', query: q })
        } else if (q === null && stateRef.current.searchQuery) {
          dispatch({ type: 'SET_SEARCH_QUERY', query: '' })
        }
      } catch {}
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    if (!state.authed) return
    if (state.page === 'settings' && !stateRef.current.adminEnv) loadEnv()
  }, [state.authed, state.page])

  // Persist the transfer panel (rows + summary + minimized) so a refresh —
  // minimized strip included — brings back the same panel. Cleared on
  // dismiss and once the queue and summary are both gone.
  useEffect(() => {
    try {
      if (!state.transferQueue.length && !state.transferSummary) {
        localStorage.removeItem(TRANSFER_SNAPSHOT_KEY)
        return
      }
      localStorage.setItem(
        TRANSFER_SNAPSHOT_KEY,
        JSON.stringify({
          queue: state.transferQueue,
          summary: state.transferSummary,
          minimized: !!state.transferMinimized,
        })
      )
    } catch {}
  }, [state.transferQueue, state.transferSummary, state.transferMinimized])

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    // Reschedule fade-out for restored done rows; a backend reconcile for a
    // still-live move follows in checkConnection via restoreTransfer().
    try {
      const snap = readTransferSnapshot()
      if (snap) scheduleTransferRemovals(sanitizeRestoredQueue(snap.queue))
    } catch {}
    checkConnection()
    return () => {
      if (timers.current.scanPoll) clearTimeout(timers.current.scanPoll)
      if (timers.current.confirmPoll) clearTimeout(timers.current.confirmPoll)
      Object.values(timers.current.transferRemoval || {}).forEach(clearTimeout)
      if (timers.current.scanEs) {
        try { timers.current.scanEs.close() } catch { /* already closed */ }
        timers.current.scanEs = null
      }
      if (timers.current.confirmEs) {
        try { timers.current.confirmEs.close() } catch { /* already closed */ }
        timers.current.confirmEs = null
      }
    }
  }, [])

  const actions = {
    toast,
    log,
    toggleLogs,
    copyText,
    checkConnection,
    dismissSetup,
    login,
    logout,
    loadLibraries,
    triggerLibraryScan,
    startScan,
    pollScanProgress,
    fetchReport,
    undoScan,
    toggleGroup,
    toggleAllGroups,
    selectItem,
    toggleGroupSelect,
    setCheckedItems,
    onTargetInputChange,
    toggleLink,
    applyGroupTargetEdits,
    confirmSelected,
    confirmGroup,
    openConfirmModal,
    closeConfirmModal,
    runConfirm,
    pollConfirmProgress,
    setTransferMinimized,
    dismissTransfer,
    deleteSourceItem,
    deleteSelectedSkipped,
    openBrowse,
    closeBrowse,
    retargetItem,
    setPage,
    setNavMenu,
    setFilter,
    setSearchQuery,
    loadEnv,
    saveEnv,
  }

  return <AppStoreContext.Provider value={{ state, actions }}>{children}</AppStoreContext.Provider>
}

export function useAppStore() {
  const ctx = useContext(AppStoreContext)
  if (!ctx) throw new Error('useAppStore must be used within AppStoreProvider')
  return ctx
}
