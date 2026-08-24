import { describe, it, expect } from 'vitest'
import {
  computePathSync,
  defaultSelection,
  groupItems,
  isCrossDriveItem,
  mapReportItems,
  matchesFilter,
  itemSearchText,
} from './report.js'

const REPORT = {
  summary: { scan_id: 'scan1', movies: 1, series: 1, skipped: 1, action_required: 2 },
  items: [
    {
      confirmId: 'c1',
      action: 'move',
      itemType: 'series',
      sourcePath: '/media1/downloads/Show.S01E01.mkv',
      targetPath: '/media1/series/Show Name (2020)/Season 01/Show Name S01E01.mkv',
      pathExists: 'Show ✗, Season ✗, File ✗',
      fileExists: false,
      fileSize: 1073741824,
      crossDrive: true,
      suspect: true,
      flags: ['phantom_show_folder', 'season_gap'],
      correctionNote: 'Likely continuation of an existing franchise',
      candidateTargets: [
        {
          path: '/media1/series/Franchise Show/Season 20/Franchise Show S20E01.mkv',
          label: 'Franchise Show',
          evidence: 'season 20 present; arc matches',
          reclassify_as_movie: true,
        },
        {
          path: '/media1/series/Show Name (2020)/Season 01/Show Name S01E01.mkv',
          label: 'New folder: Show Name (2020)',
          evidence: '',
          reclassify_as_movie: false,
        },
      ],
    },
    {
      confirmId: 'c2',
      action: 'replace',
      itemType: 'movie',
      sourcePath: '/media2/downloads/Movie.mkv',
      targetPath: '/media2/movies/Movie (2024)/Movie.mkv',
      pathExists: 'Folder ✓, File ✓',
      fileExists: true,
      fileSize: 536870912,
      crossDrive: false,
    },
    {
      confirmId: 'c3',
      action: 'skip',
      itemType: 'series',
      sourcePath: '/media3/downloads/Bad.mkv',
      error: 'No season folder found',
      fileSize: 12345,
    },
  ],
}

function buildItems() {
  return mapReportItems(REPORT)
}

function itemWithTargets(cloneBase) {
  return cloneBase.map((i) => ({ ...i, _liveTarget: i.targetPath }))
}

describe('mapReportItems', () => {
  it('derives title/season/episode from series target path', () => {
    const [series] = buildItems()
    expect(series.title).toBe('Show Name (2020)')
    expect(series.season).toBe('Season 01')
    expect(series.episode).toBe('S01E01')
    expect(series.sourceName).toBe('Show.S01E01.mkv')
    expect(series.crossDrive).toBe(true)
  })

  it('derives movie title from target path', () => {
    const [, movie] = buildItems()
    expect(movie.title).toBe('Movie (2024)')
    expect(movie.action).toBe('replace')
    expect(movie.fileExists).toBe(true)
  })

  it('maps skipped items with reason', () => {
    const items = buildItems()
    const skip = items.find((i) => i.action === 'skip')
    expect(skip.reason).toBe('No season folder found')
    expect(skip.title).toBe('Skipped items')
  })

  it('passes through smart-correction fields (flags, suspect, candidates)', () => {
    const [series] = buildItems()
    expect(series.suspect).toBe(true)
    expect(series.flags).toEqual(['phantom_show_folder', 'season_gap'])
    expect(series.correctionNote).toBe('Likely continuation of an existing franchise')
    expect(series.candidateTargets).toHaveLength(2)
    expect(series.candidateTargets[0].path).toBe('/media1/series/Franchise Show/Season 20/Franchise Show S20E01.mkv')
    expect(series.candidateTargets[0].label).toBe('Franchise Show')
    expect(series.candidateTargets[0].evidence).toContain('season 20 present')
    expect(series.candidateTargets[0].reclassify_as_movie).toBe(true)
  })

  it('defaults candidates/flags to empty when absent', () => {
    const items = buildItems()
    const movie = items.find((i) => i.action === 'replace')
    expect(movie.candidateTargets).toEqual([])
    expect(movie.flags).toEqual([])
    expect(movie.suspect).toBe(false)
    expect(movie.corrected).toBe(false)
  })
})

describe('groupItems', () => {
  it('groups by title and sums size (newest first)', () => {
    const groups = groupItems(buildItems())
    // Newest (highest _idx) first — incremental scans surface new files at the top
    expect(groups.map((g) => g.title)).toEqual(['Skipped items', 'Movie (2024)', 'Show Name (2020)'])
    expect(groups.find((g) => g.title === 'Show Name (2020)').totalSize).toBe(1073741824)
  })
})

describe('matchesFilter', () => {
  const [c1, c2] = buildItems()
  const [series, movie] = [c1, c2]

  it('filters by query text', () => {
    expect(matchesFilter(movie, 'Movie (2024)', 'all')).toBe(true)
    expect(matchesFilter(movie, 'Show Name', 'all')).toBe(false)
  })

  it('filters by action axis', () => {
    expect(matchesFilter(series, '', 'move')).toBe(true)
    expect(matchesFilter(movie, '', 'move')).toBe(false)
    expect(matchesFilter(movie, '', 'replace')).toBe(true)
  })

  it('filters by fileExists axis', () => {
    expect(matchesFilter(movie, '', 'existing')).toBe(true)
    expect(matchesFilter(series, '', 'existing')).toBe(false)
    expect(matchesFilter(series, '', 'new')).toBe(true)
  })
})

describe('defaultSelection', () => {
  it('selects actionable items only', () => {
    const items = itemWithTargets(buildItems())
    expect(defaultSelection(items)).toEqual(['c1', 'c2'])
  })
})

describe('isCrossDriveItem', () => {
  it('trusts the backend flag when the target is unchanged', () => {
    const items = itemWithTargets(buildItems())
    expect(isCrossDriveItem(items[0])).toBe(true)
    expect(isCrossDriveItem(items[1])).toBe(false)
  })

  it('detects cross-drive from an edited live target', () => {
    const items = itemWithTargets(buildItems())
    items[1]._liveTarget = '/media3/movies/Movie (2024)/Movie.mkv'
    expect(isCrossDriveItem(items[1])).toBe(true)
  })

  it('lets the drive roots win over a stale backend flag once the target is edited', () => {
    const items = itemWithTargets(buildItems())
    items[0]._liveTarget = '/media1/series/Show Name (2020)/Season 02/Show Name S01E01.mkv'
    expect(isCrossDriveItem(items[0])).toBe(false)
  })
})

describe('computePathSync', () => {
  function seriesRows() {
    const base = buildItems()
    const items = itemWithTargets(base)
    items[0].title = 'Show Name (2020)'
    items[0].sourceFolder = 'Show.S01'
    items[0].containerPath = '/media1/torrents/Show.S01'
    items[1].title = 'Show Name (2020)'
    items[1].sourceFolder = 'Show.S01'
    items[1].containerPath = '/media1/torrents/Show.S01'
    items[0].targetPath = '/media1/series/Show Name (2020)/Season 01/Show Name S01E01.mkv'
    items[0]._liveTarget = items[0].targetPath
    items[1].targetPath = '/media1/series/Show Name (2020)/Season 01/Show Name S01E02.mkv'
    items[1]._liveTarget = items[1].targetPath
    return items
  }

  it('syncs a changed chunk to sibling rows in the same group', () => {
    const items = seriesRows()
    const synced = computePathSync(
      0,
      items[0]._liveTarget,
      '/media1/series/Show Name (2021)/Season 01/Show Name S01E01.mkv',
      items
    )
    expect(synced).not.toBeNull()
    expect(synced.updates.length).toBe(1)
    expect(synced.updates[0].idx).toBe(1)
    expect(synced.updates[0].value).toBe('/media1/series/Show Name (2021)/Season 01/Show Name S01E02.mkv')
  })

  it('reverts when no sibling shares the changed chunk', () => {
    const items = seriesRows()
    const synced = computePathSync(0, items[0]._liveTarget, '/totally/different/path/Show.mkv', items)
    expect(synced).toEqual({ revert: true })
  })

  it('keeps the edit (no revert) when the row is alone in its group', () => {
    const items = seriesRows()
    items[1].sourceFolder = 'Other.S01'
    items[1].containerPath = '/media1/torrents/Other.S01'
    items[1].title = 'Other Show'
    items[1]._liveTarget = '/media1/series/Other Show/Season 01/Other Show S01E01.mkv'
    items[1].targetPath = items[1]._liveTarget
    const synced = computePathSync(
      0,
      items[0]._liveTarget,
      '/media2/series/Show Name (2020)/Season 01/Show Name S01E01.mkv',
      items
    )
    expect(synced).toBeNull()
  })

  it('does not touch rows in other groups even when the prefix matches', () => {
    const items = seriesRows()
    items[1].sourceFolder = 'Show.S01'
    items[1].containerPath = '/media1/torrents/Show.S01'
    items[1].title = 'Show Name (2020)'
    const other = itemWithTargets(buildItems())
    items.push({
      ...other[1],
      title: 'Other Show',
      sourceFolder: 'Other.S01',
      containerPath: '/media1/torrents/Other.S01',
      _liveTarget: '/media1/series/Show Name (2020)/Season 01/Show Name S01E03.mkv',
    })
    const synced = computePathSync(
      0,
      items[0]._liveTarget,
      '/media1/series/Show Name (2021)/Season 01/Show Name S01E01.mkv',
      items
    )
    expect(synced.updates.length).toBe(1)
    expect(synced.updates[0].idx).toBe(1)
    expect(synced.updates.every((u) => (items[u.idx].sourceFolder || items[u.idx].containerPath) === 'Show.S01')).toBe(true)
  })

  it('returns null when value is unchanged', () => {
    const items = seriesRows()
    expect(computePathSync(0, items[0]._liveTarget, items[0]._liveTarget, items)).toBe(null)
  })

  it('does not sync when the changed row is unlinked', () => {
    const items = seriesRows()
    items[0]._linked = false
    const synced = computePathSync(
      0,
      items[0]._liveTarget,
      '/media1/series/Show Name (2021)/Season 01/Show Name S01E01.mkv',
      items
    )
    expect(synced).toBeNull()
  })

  it('does not sync to an unlinked sibling', () => {
    const items = seriesRows()
    items[1]._linked = false
    const synced = computePathSync(
      0,
      items[0]._liveTarget,
      '/media1/series/Show Name (2021)/Season 01/Show Name S01E01.mkv',
      items
    )
    expect(synced).toBeNull()
  })

  it('syncs only to linked siblings, skipping unlinked ones', () => {
    const items = seriesRows().slice(0, 2)
    // third sibling in same group
    const third = { ...items[0], _liveTarget: '/media1/series/Show Name (2020)/Season 01/Show Name S01E03.mkv', targetPath: '/media1/series/Show Name (2020)/Season 01/Show Name S01E03.mkv', sourceFolder: 'Show.S01', containerPath: '/media1/torrents/Show.S01', title: 'Show Name (2020)', _linked: true }
    items.push(third)
    items[1]._linked = false
    const synced = computePathSync(
      0,
      items[0]._liveTarget,
      '/media1/series/Show Name (2021)/Season 01/Show Name S01E01.mkv',
      items
    )
    expect(synced).not.toBeNull()
    expect(synced.updates.length).toBe(1)
    expect(synced.updates[0].idx).toBe(2)
  })

  it('keeps edit when all linked siblings are gone (only unlinked remain) — no revert', () => {
    const items = seriesRows()
    items[1]._linked = false
    const synced = computePathSync(0, items[0]._liveTarget, '/totally/different/path/Show.mkv', items)
    // No linked sibling exists, so revert should not trigger — return null (keep edit)
    expect(synced).toBeNull()
  })
})

describe('itemSearchText', () => {
  it('includes title, episode and paths', () => {
    const [series] = buildItems()
    const text = itemSearchText(series)
    expect(text).toContain('show name (2020)')
    expect(text).toContain('s01e01')
    expect(text).toContain('/media1/series')
  })
})
