import { describe, it, expect } from 'vitest'
import {
  bringNewGroupsToTop,
  compareReportItemsAsc,
  computePathSync,
  defaultSelection,
  groupItems,
  isCrossDriveItem,
  isLockedItem,
  joinTarget,
  mapReportItems,
  matchesFilter,
  itemSearchText,
  splitTarget,
  summarizeReportDiff,
  typeLabelFor,
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

  it('maps type labels for the Type column', () => {
    const items = buildItems()
    const series = items.find((i) => i.confirmId === 'c1')
    const movie = items.find((i) => i.confirmId === 'c2')
    const skip = items.find((i) => i.action === 'skip')
    expect(series.typeLabel).toBe('S01E01')
    expect(movie.typeLabel).toBe('Movie')
    // c3 is a series-kind skip without a target, so it falls back to the kind label
    expect(skip.typeLabel).toBe('Series')
    expect(typeLabelFor({ itemType: 'skip' })).toBe('—')
  })

  it('passes through extraType and labels extras', () => {
    const report = {
      summary: {},
      items: [
        { confirmId: 'x1', action: 'move', itemType: 'extra', extraType: 'trailer', sourcePath: '/d/x.mkv', targetPath: '/s/Show/Extras/x.mkv' },
      ],
    }
    const [extra] = mapReportItems(report)
    expect(extra.extraType).toBe('trailer')
    expect(extra.typeLabel).toBe('Extra · trailer')
  })
})

describe('groupItems', () => {
  it('groups by title and sums size (newest group first)', () => {
    const groups = groupItems(buildItems())
    // Newest group (highest _idx) first — incremental scans surface new files at the top
    expect(groups.map((g) => g.title)).toEqual(['Skipped items', 'Movie (2024)', 'Show Name (2020)'])
    expect(groups.find((g) => g.title === 'Show Name (2020)').totalSize).toBe(1073741824)
  })

  it('sorts rows within a group ascending (S01E01 before S01E02)', () => {
    const items = [
      { confirmId: 'e2', title: 'Show', sourceFolder: 'Pack', targetPath: '/s/Show/Season 01/Show S01E02.mkv', itemType: 'series', episode: 'S01E02', action: 'move' },
      { confirmId: 'e10', title: 'Show', sourceFolder: 'Pack', targetPath: '/s/Show/Season 01/Show S01E10.mkv', itemType: 'series', episode: 'S01E10', action: 'move' },
      { confirmId: 'e1', title: 'Show', sourceFolder: 'Pack', targetPath: '/s/Show/Season 01/Show S01E01.mkv', itemType: 'series', episode: 'S01E01', action: 'move' },
    ]
    const [group] = groupItems(items)
    expect(group.items.map((i) => i.confirmId)).toEqual(['e1', 'e2', 'e10'])
  })

  it('sorts series before movies before extras within a mixed group', () => {
    const items = [
      { confirmId: 'x1', title: 'Pack', sourceFolder: 'Pack', targetPath: '/m/Extra.mkv', itemType: 'extra', action: 'move' },
      { confirmId: 'm1', title: 'Pack', sourceFolder: 'Pack', targetPath: '/m/Movie (2024)/Movie.mkv', itemType: 'movie', action: 'move' },
      { confirmId: 's1', title: 'Pack', sourceFolder: 'Pack', targetPath: '/s/Show/Season 01/Show S01E01.mkv', itemType: 'series', episode: 'S01E01', action: 'move' },
    ]
    const [group] = groupItems(items)
    expect(group.items.map((i) => i.confirmId)).toEqual(['s1', 'm1', 'x1'])
  })
})

describe('typeLabelFor', () => {
  it('shows the episode tag for series', () => {
    expect(typeLabelFor({ itemType: 'series', episode: 'S01E04', targetPath: '/s/Show/Season 01/x.mkv' })).toBe('S01E04')
  })

  it('uppercases a lowercase episode tag from the target path', () => {
    expect(typeLabelFor({ itemType: 'series', targetPath: '/s/Show/Season 01/Show s01e04.mkv' })).toBe('S01E04')
  })

  it('falls back to Series when no episode is parseable', () => {
    expect(typeLabelFor({ itemType: 'series', targetPath: '/s/Show/Season 01/x.mkv' })).toBe('Series')
  })

  it('shows Movie for movies', () => {
    expect(typeLabelFor({ itemType: 'movie', targetPath: '/m/Movie (2024)/Movie.mkv' })).toBe('Movie')
  })

  it('shows Extra, with the extra-type suffix when present', () => {
    expect(typeLabelFor({ itemType: 'extra', targetPath: '/s/Show/Extras/x.mkv' })).toBe('Extra')
    expect(typeLabelFor({ itemType: 'extra', extraType: 'trailer', targetPath: '/s/Show/Extras/x.mkv' })).toBe('Extra · trailer')
  })

  it('reads snake_case history shapes', () => {
    expect(typeLabelFor({ item_type: 'movie', target_path: '/m/Movie/Movie.mkv' })).toBe('Movie')
    expect(typeLabelFor({ item_type: 'series', target_path: '/s/Show/Season 02/Show s02e03.mkv' })).toBe('S02E03')
    expect(typeLabelFor({ item_type: 'extra', extra_type: 'featurette', target_path: '/s/Show/Extras/x.mkv' })).toBe('Extra · featurette')
  })

  it('shows an em dash for skips', () => {
    expect(typeLabelFor({ itemType: 'skip' })).toBe('—')
  })
})

describe('compareReportItemsAsc', () => {
  it('orders S01E10 before S02E01 numerically', () => {
    const a = { itemType: 'series', episode: 'S01E10', targetPath: '/s/Show/Season 01/Show S01E10.mkv' }
    const b = { itemType: 'series', episode: 'S02E01', targetPath: '/s/Show/Season 02/Show S02E01.mkv' }
    expect(compareReportItemsAsc(a, b)).toBeLessThan(0)
    expect(compareReportItemsAsc(b, a)).toBeGreaterThan(0)
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

  it('keeps a solo generic-root edit (lanterns) — same sourceFolder, different titles, no sync/no revert', () => {
    const items = [
      { confirmId: 'r1', title: 'Rent-a-Girlfriend', sourceFolder: 'torrents', containerPath: '', targetPath: '/m2/series-r/Rent-a-Girlfriend/Season 05/Rent-a-Girlfriend - S05E12.mkv', _liveTarget: '/m2/series-r/Rent-a-Girlfriend/Season 05/Rent-a-Girlfriend - S05E12.mkv', itemType: 'series', action: 'move' },
      { confirmId: 'l1', title: 'Lanterns (2026)', sourceFolder: 'torrents', containerPath: '', targetPath: '/m3/series/Lanterns (2026)/Season 01/lanterns - S01E06.mkv', _liveTarget: '/m3/series/Lanterns (2026)/Season 01/lanterns - S01E06.mkv', itemType: 'series', action: 'move' },
    ]
    // Rendered groups split generic 'torrents' by title, so Lanterns is solo (group size 1, no link icon)
    const groups = groupItems(items)
    expect(groups.find((g) => g.title === 'Lanterns (2026)').items).toHaveLength(1)
    const synced = computePathSync(
      1,
      items[1]._liveTarget,
      '/m3/series/Lanterns (2026)/Season 01/lanterns - S01E06-edited.mkv',
      items
    )
    expect(synced).toBeNull()
  })
})

describe('summarizeReportDiff', () => {
  const prev = [
    { sourcePath: '/d/Show.S01E01.mkv', action: 'move', targetPath: '/s/Show/Season 01/Show S01E01.mkv' },
    { sourcePath: '/d/Movie.mkv', action: 'skip', targetPath: '' },
  ]

  it('counts unseen sources as new and changed ones as updated', () => {
    const next = [
      { sourcePath: '/d/Show.S01E01.mkv', action: 'move', targetPath: '/s/Show/Season 01/Show S01E01.mkv' },
      { sourcePath: '/d/Movie.mkv', action: 'move', targetPath: '/m/Movie/Movie.mkv' },
      { sourcePath: '/d/Fresh.S01E01.mkv', action: 'move', targetPath: '/s/Fresh/Season 01/Fresh S01E01.mkv' },
    ]
    const diff = summarizeReportDiff(prev, next)
    expect(diff.newCount).toBe(1)
    expect(diff.updatedCount).toBe(1)
    expect(diff.newSources.has('/d/Fresh.S01E01.mkv')).toBe(true)
  })

  it('reports zeroes when nothing changed', () => {
    const diff = summarizeReportDiff(prev, [...prev])
    expect(diff.newCount).toBe(0)
    expect(diff.updatedCount).toBe(0)
    expect(diff.newSources.size).toBe(0)
  })

  it('reads snake_case history shapes', () => {
    const diff = summarizeReportDiff(
      [{ source_path: '/d/a.mkv', action: 'move', target_path: '/s/A.mkv' }],
      [{ source_path: '/d/a.mkv', action: 'move', target_path: '/s/A.mkv' }],
    )
    expect(diff.newCount).toBe(0)
    expect(diff.updatedCount).toBe(0)
  })
})

describe('bringNewGroupsToTop', () => {
  function groups() {
    return [
      { title: 'Old Show', items: [{ sourcePath: '/d/Old.S01E01.mkv' }] },
      { title: 'Fresh Show', items: [{ sourcePath: '/d/Fresh.S01E01.mkv' }] },
    ]
  }

  it('lifts groups with new sources first, keeping order otherwise', () => {
    const ordered = bringNewGroupsToTop(groups(), new Set(['/d/Fresh.S01E01.mkv']))
    expect(ordered.map((g) => g.title)).toEqual(['Fresh Show', 'Old Show'])
  })

  it('returns groups untouched when nothing is new', () => {
    const input = groups()
    expect(bringNewGroupsToTop(input, new Set())).toBe(input)
    expect(bringNewGroupsToTop(input, new Set(['/d/Other.mkv']))).toBe(input)
  })
})
describe('splitTarget/joinTarget', () => {
  const ROOTS = [
    { key: 's2', path: '/mnt/media2t/downloads/series', kind: 'series', description: 'Series' },
    { key: 'm2', path: '/mnt/media2t/downloads/movies', kind: 'movie', description: 'Movies' },
  ]

  it('splits the library prefix from the remainder', () => {
    expect(splitTarget('/mnt/media2t/downloads/series/Toshi Densetsu Series/Season 01/Toshi .mp4', ROOTS)).toEqual({
      root: '/mnt/media2t/downloads/series/',
      remainder: 'Toshi Densetsu Series/Season 01/Toshi .mp4',
    })
  })

  it('round-trips through joinTarget', () => {
    const { root, remainder } = splitTarget('/mnt/media2t/downloads/series/Show/Season 01/f.mkv', ROOTS)
    expect(joinTarget(root, remainder)).toBe('/mnt/media2t/downloads/series/Show/Season 01/f.mkv')
  })

  it('swaps only the prefix when the root changes', () => {
    const { remainder } = splitTarget('/mnt/media2t/downloads/series/Show/Season 01/f.mkv', ROOTS)
    expect(joinTarget('/mnt/media1t/downloads/series/', remainder)).toBe(
      '/mnt/media1t/downloads/series/Show/Season 01/f.mkv'
    )
  })

  it('strips leading slashes from the remainder so edits never escape the root', () => {
    expect(joinTarget('/mnt/media2t/downloads/series/', '/Show/f.mkv')).toBe(
      '/mnt/media2t/downloads/series/Show/f.mkv'
    )
  })

  it('returns an empty remainder when the target is exactly the root', () => {
    expect(splitTarget('/mnt/media2t/downloads/series', ROOTS)).toEqual({
      root: '/mnt/media2t/downloads/series/',
      remainder: '',
    })
  })

  it('falls back to custom when outside all roots', () => {
    expect(splitTarget('/tmp/other/f.mkv', ROOTS)).toEqual({ root: '', remainder: '/tmp/other/f.mkv' })
    expect(joinTarget('', '/tmp/other/f.mkv')).toBe('/tmp/other/f.mkv')
  })

  it('prefers the longest matching root', () => {
    const nested = [...ROOTS, '/mnt/media2t/downloads/series/Show']
    expect(splitTarget('/mnt/media2t/downloads/series/Show/Season 01/f.mkv', nested)).toEqual({
      root: '/mnt/media2t/downloads/series/Show/',
      remainder: 'Season 01/f.mkv',
    })
  })

  it('accepts plain string roots', () => {
    expect(splitTarget('/a/b/f.mkv', ['/a/b'])).toEqual({ root: '/a/b/', remainder: 'f.mkv' })
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
  it('matches type labels such as movie and extra', () => {
    const items = buildItems()
    const movie = items.find((i) => i.confirmId === 'c2')
    expect(itemSearchText(movie)).toContain('movie')
    expect(itemSearchText({ itemType: 'extra', extraType: 'trailer', targetPath: '/s/Show/Extras/x.mkv', typeLabel: 'Extra · trailer' })).toContain('trailer')
  })
})

describe('editable skips (plan 17)', () => {
  const EDITABLE_REPORT = {
    summary: {},
    items: [
      {
        confirmId: 'e1',
        action: 'skip',
        locked: false,
        itemType: 'extra',
        extraType: 'sample',
        sourcePath: '/d/Show/file-sample.mkv',
        targetPath: '/s/Show/samples/file-sample.mkv',
        candidateTargets: [],
        flags: [],
      },
      {
        confirmId: 'e2',
        action: 'skip',
        locked: true,
        itemType: 'skip',
        sourcePath: '/d/other.mkv.!qB',
        reason: 'In-progress download',
      },
    ],
  }

  it('isLockedItem defaults missing locked to locked, false stays editable', () => {
    expect(isLockedItem({ action: 'skip' })).toBe(true)
    expect(isLockedItem({ action: 'skip', locked: true })).toBe(true)
    expect(isLockedItem({ action: 'skip', locked: false })).toBe(false)
    expect(isLockedItem({ action: 'move', locked: true })).toBe(false)
  })

  it('maps unlocked skips with their proposed target and title', () => {
    const items = mapReportItems(EDITABLE_REPORT)
    const editable = items.find((i) => i.confirmId === 'e1')
    expect(editable.locked).toBe(false)
    expect(editable.targetPath).toBe('/s/Show/samples/file-sample.mkv')
    // Extra titles derive from the parent folder (same as actionable extras)
    expect(editable.title).toBe('samples')
    expect(editable.typeLabel).toBe('Extra · sample')
    const locked = items.find((i) => i.confirmId === 'e2')
    expect(locked.locked).toBe(true)
    expect(locked.title).toBe('Skipped items')
    expect(locked.targetPath).toBe('')
  })

  it('keeps unlocked skips out of the default confirm selection', () => {
    const items = mapReportItems(EDITABLE_REPORT)
    expect(defaultSelection(items)).toEqual([])
  })
})
