// reportSlice — extracted from AppStore for long-horizon maintainability
// Keeps reportVisible, reportAll, reportSummary, reportServiceErrors, currentItems,
// reportGroups, selectedIds, expandedGroups, currentFilter/searchQuery and their helpers.
// Pure reducers + helpers, no side effects.
import { groupItems } from '../../utils/report.js'

export const reportInitialState = {
  reportVisible: false,
  reportAll: [],
  reportSummary: null,
  reportServiceErrors: null,
  currentItems: [],
  reportGroups: [],
  selectedIds: [],
  expandedGroups: [],
  // currentFilter/searchQuery are initialized in AppStore with URL/localStorage; keep defaults here for tests
  currentFilter: 'all',
  searchQuery: '',
}

export function reportReducer(state, action) {
  switch (action.type) {
    case 'SET_REPORT':
      // payload may contain reportVisible, reportAll, reportSummary, reportServiceErrors, currentItems, reportGroups, selectedIds, expandedGroups, scanId
      return { ...state, ...action.payload, reportLoading: false }
    case 'SET_SELECTION':
      return { ...state, selectedIds: action.selectedIds }
    case 'SET_ITEMS':
      return { ...state, currentItems: action.currentItems, reportGroups: action.reportGroups }
    case 'SET_PATH_STATUS': {
      // Merge live path-status pills into CURRENT items (race-free).
      // A whole-array replace here would clobber a concurrent dispatch
      // (e.g. Update Paths saving while a status preview resolves), so match
      // by confirmId and only touch rows whose live target still equals the
      // checked target.
      const byId = new Map((action.updates || []).map((u) => [u.confirmId, u]))
      const currentItems = state.currentItems.map((it) => {
        const u = byId.get(it.confirmId)
        if (!u) return it
        const live = it._liveTarget || it.targetPath
        if ((live || '').trim() !== u.target) return it
        return {
          ...it,
          pathExists: u.pathExists ?? it.pathExists,
          showFolderExists: u.showFolderExists ?? it.showFolderExists,
          seasonFolderExists: u.seasonFolderExists ?? it.seasonFolderExists,
          fileExists: u.fileExists ?? it.fileExists,
          _statusCheckedFor: u.target,
        }
      })
      return { ...state, currentItems, reportGroups: groupItems(currentItems) }
    }
    case 'TOGGLE_GROUP': {
      const list = state.expandedGroups.includes(action.gid)
        ? state.expandedGroups.filter(v => v !== action.gid)
        : [...state.expandedGroups, action.gid]
      return { ...state, expandedGroups: list }
    }
    case 'SET_GROUPS_EXPANDED':
      return { ...state, expandedGroups: action.list }
    case 'SET_FILTER':
      return { ...state, currentFilter: action.filter }
    case 'SET_SEARCH_QUERY':
      return { ...state, searchQuery: action.query }
    default:
      return state
  }
}

// Helpers that were previously inline in AppStore — now testable
export function toggleInList(list, value) {
  return list.includes(value) ? list.filter(v => v !== value) : [...list, value]
}
