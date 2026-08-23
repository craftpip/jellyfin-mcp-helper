// reportSlice — extracted from AppStore for long-horizon maintainability
// Keeps reportVisible, reportAll, reportSummary, reportServiceErrors, currentItems,
// reportGroups, selectedIds, expandedGroups, currentFilter, searchQuery and their helpers.
// Pure reducers + helpers, no side effects.

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
