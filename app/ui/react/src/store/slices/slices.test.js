import { describe, it, expect } from 'vitest'
import { reportReducer, reportInitialState, toggleInList } from './reportSlice.js'
import { scanReducer, scanInitialState } from './scanSlice.js'
import { adminReducer, adminInitialState } from './adminSlice.js'

describe('reportSlice', () => {
  it('SET_REPORT merges payload and clears reportLoading', () => {
    const state = reportReducer(
      { ...reportInitialState, reportLoading: true },
      { type: 'SET_REPORT', payload: { reportVisible: true, reportAll: [{ id: 1 }], reportSummary: { total: 1 } } }
    )
    expect(state.reportVisible).toBe(true)
    expect(state.reportAll).toHaveLength(1)
    expect(state.reportLoading).toBe(false)
  })

  it('SET_SELECTION replaces selectedIds', () => {
    const state = reportReducer(reportInitialState, { type: 'SET_SELECTION', selectedIds: ['a', 'b'] })
    expect(state.selectedIds).toEqual(['a', 'b'])
  })

  it('SET_ITEMS replaces currentItems and reportGroups', () => {
    const items = [{ id: 1 }]
    const groups = [{ title: 'g', items }]
    const state = reportReducer(reportInitialState, { type: 'SET_ITEMS', currentItems: items, reportGroups: groups })
    expect(state.currentItems).toBe(items)
    expect(state.reportGroups).toBe(groups)
  })

  it('SET_PATH_STATUS merges pills by confirmId without touching other fields', () => {
    const base = {
      ...reportInitialState,
      currentItems: [
        {
          confirmId: 'c1',
          action: 'move',
          itemType: 'series',
          targetPath: '/s/Show/Season 01/Show - S01E01.mkv',
          originalTarget: '/s/Show/Season 01/Show - S01E01.mkv',
          _liveTarget: '/s/Show/Season 01/Show - S01E01.mkv',
          pathExists: 'Show ✗, Season ✗, File ✗',
        },
        {
          confirmId: 'c2',
          action: 'move',
          itemType: 'series',
          targetPath: '/s/Show/Season 01/Show - S01E02.mkv',
          originalTarget: '/s/Show/Season 01/Show - S01E02.mkv',
          _liveTarget: '/s/Show/Season 01/Show - S01E02.mkv',
          pathExists: 'Show ✗, Season ✗, File ✗',
        },
      ],
    }
    const state = reportReducer(base, {
      type: 'SET_PATH_STATUS',
      updates: [
        {
          confirmId: 'c2',
          target: '/s/Show/Season 01/Show - S01E02.mkv',
          pathExists: 'Show ✓, Season ✓, File ✗',
          showFolderExists: true,
          seasonFolderExists: true,
          fileExists: false,
        },
      ],
    })
    const [c1, c2] = state.currentItems
    // Untouched row keeps everything
    expect(c1.pathExists).toBe('Show ✗, Season ✗, File ✗')
    expect(c1._statusCheckedFor).toBeUndefined()
    // Linked sibling row gets fresh pills + checked marker, live target intact
    expect(c2.pathExists).toBe('Show ✓, Season ✓, File ✗')
    expect(c2.showFolderExists).toBe(true)
    expect(c2._statusCheckedFor).toBe('/s/Show/Season 01/Show - S01E02.mkv')
    expect(c2._liveTarget).toBe('/s/Show/Season 01/Show - S01E02.mkv')
    expect(c2.originalTarget).toBe('/s/Show/Season 01/Show - S01E02.mkv')
  })

  it('SET_PATH_STATUS skips rows whose live target moved on', () => {
    const base = {
      ...reportInitialState,
      currentItems: [
        {
          confirmId: 'c1',
          action: 'move',
          itemType: 'movie',
          targetPath: '/m/A/A.mkv',
          _liveTarget: '/m/B/B.mkv',
          pathExists: 'Folder ✗, File ✗',
        },
      ],
    }
    const state = reportReducer(base, {
      type: 'SET_PATH_STATUS',
      updates: [{ confirmId: 'c1', target: '/m/A/A.mkv', pathExists: 'Folder ✓, File ✗' }],
    })
    expect(state.currentItems[0].pathExists).toBe('Folder ✗, File ✗')
    expect(state.currentItems[0]._statusCheckedFor).toBeUndefined()
  })

  it('TOGGLE_GROUP adds gid when absent', () => {
    const state = reportReducer(reportInitialState, { type: 'TOGGLE_GROUP', gid: 'group-0' })
    expect(state.expandedGroups).toEqual(['group-0'])
  })

  it('TOGGLE_GROUP removes gid when present', () => {
    const state = reportReducer(
      { ...reportInitialState, expandedGroups: ['group-0', 'group-1'] },
      { type: 'TOGGLE_GROUP', gid: 'group-0' }
    )
    expect(state.expandedGroups).toEqual(['group-1'])
  })

  it('SET_GROUPS_EXPANDED replaces the list', () => {
    const state = reportReducer(reportInitialState, { type: 'SET_GROUPS_EXPANDED', list: ['a', 'b', 'c'] })
    expect(state.expandedGroups).toEqual(['a', 'b', 'c'])
  })

  it('SET_FILTER sets currentFilter', () => {
    const state = reportReducer(reportInitialState, { type: 'SET_FILTER', filter: 'move' })
    expect(state.currentFilter).toBe('move')
  })

  it('SET_SEARCH_QUERY sets searchQuery', () => {
    const state = reportReducer(reportInitialState, { type: 'SET_SEARCH_QUERY', query: 'hello' })
    expect(state.searchQuery).toBe('hello')
  })

  it('unknown action returns state unchanged', () => {
    const state = { ...reportInitialState }
    expect(reportReducer(state, { type: 'NOPE' })).toBe(state)
  })

  it('toggleInList adds value when absent', () => {
    expect(toggleInList(['a', 'b'], 'c')).toEqual(['a', 'b', 'c'])
  })

  it('toggleInList removes value when present', () => {
    expect(toggleInList(['a', 'b', 'c'], 'b')).toEqual(['a', 'c'])
  })
})

describe('scanSlice', () => {
  it('SET_SCAN_ID sets scanId', () => {
    const state = scanReducer(scanInitialState, { type: 'SET_SCAN_ID', scanId: 'abc' })
    expect(state.scanId).toBe('abc')
  })

  it('SET_SCAN_RUNNING sets scanRunning', () => {
    const state = scanReducer(scanInitialState, { type: 'SET_SCAN_RUNNING', scanRunning: true })
    expect(state.scanRunning).toBe(true)
  })

  it('SET_SCAN_PROGRESS sets scanProgress', () => {
    const progress = { percent: 50, status: 'running' }
    const state = scanReducer(scanInitialState, { type: 'SET_SCAN_PROGRESS', progress })
    expect(state.scanProgress).toBe(progress)
  })

  it('unknown action returns state unchanged', () => {
    const state = { ...scanInitialState }
    expect(scanReducer(state, { type: 'NOPE' })).toBe(state)
  })
})

describe('adminSlice', () => {
  it('SET_ADMIN_ENV sets env and pending', () => {
    const env = { settings: {}, pending: ['JELLYFIN_BASE_URL'] }
    const state = adminReducer(adminInitialState, { type: 'SET_ADMIN_ENV', env })
    expect(state.adminEnv).toBe(env)
    expect(state.adminEnvPending).toEqual(['JELLYFIN_BASE_URL'])
  })

  it('SET_ADMIN_ENV with no pending defaults to []', () => {
    const state = adminReducer(adminInitialState, { type: 'SET_ADMIN_ENV', env: { settings: {} } })
    expect(state.adminEnvPending).toEqual([])
  })

  it('SET_ADMIN_LOADING sets loading', () => {
    const state = adminReducer(adminInitialState, { type: 'SET_ADMIN_LOADING', loading: true })
    expect(state.adminLoading).toBe(true)
  })

  it('unknown action returns state unchanged', () => {
    const state = { ...adminInitialState }
    expect(adminReducer(state, { type: 'NOPE' })).toBe(state)
  })
})
