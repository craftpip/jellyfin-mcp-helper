import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HistoryPage from './HistoryPage.jsx'
import { AppStoreProvider } from '../store/AppStore.jsx'

const GROUPS = {
  groups: [
    {
      history_id: 'h_abcdef123456',
      scan_id: 'scan1',
      group_title: 'New Show',
      group_key: '/media1/library/New Show',
      confirmed_at: new Date('2026-08-24T10:00:00Z').toISOString(),
      confirmed_by: 'panel',
      items: [
        {
          confirm_id: 'c1',
          source_path: '/media1/downloads/New.Show.S01E01.mkv',
          source_folder: 'downloads',
          target_path: '/media1/library/New Show/Season 01/New Show S01E01.mkv',
          path_history_json: '[]',
          pathHistory: [
            '/media1/downloads/New.Show.S01E01.mkv',
            '/media1/library/New Show/Season 01/New Show S01E01.mkv',
          ],
          action: 'move',
          item_type: 'series',
          file_size: 2048,
          status: 'moved',
          error: null,
          suspect: 1,
          corrected: 0,
          correction_note: null,
          cross_drive: 1,
          source_exists: true,
          target_exists: true,
          pathExists: 'Show ✓, Season ✓, File ✓',
        },
        {
          confirm_id: 'c2',
          source_path: '/media1/downloads/Old.Movie.mkv',
          source_folder: 'downloads',
          target_path: '/media1/movies/Old Movie (2019)/Old Movie.mkv',
          path_history_json: '[]',
          pathHistory: [
            '/media1/downloads/Old.Movie.mkv',
            '/media1/movies/Old Movie (2019)/Old Movie.mkv',
          ],
          action: 'replace',
          item_type: 'movie',
          file_size: null,
          status: 'replaced',
          error: null,
          suspect: 0,
          corrected: 0,
          correction_note: null,
          cross_drive: 0,
          source_exists: false,
          target_exists: true,
          pathExists: 'Folder ✓, File ✓',
        },
      ],
    },
  ],
}

const ROOTS = {
  roots: [
    { key: 's1', path: '/media1/library', kind: 'series', description: 'Series library' },
  ],
}

let posted = []

beforeEach(() => {
  posted = []
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.stubGlobal(
    'fetch',
    vi.fn((url, opts) => {
      const method = (opts?.method || 'GET').toUpperCase()
      const path = String(url)
      let payload = {}
      if (method === 'POST' && path.endsWith('/retarget')) {
        posted.push({ kind: 'retarget', body: JSON.parse(opts.body || '{}') })
        payload = { moved: 1, history_id: 'h_abcdef123456' }
      } else if (method === 'POST' && path.endsWith('/undo')) {
        posted.push({ kind: 'undo', body: JSON.parse(opts.body || '{}') })
        payload = { restored: 2, skipped: [], history_id: 'h_abcdef123456' }
      } else if (method === 'POST' && path.includes('/delete-source')) {
        posted.push({ kind: 'delete-source', body: JSON.parse(opts.body || '{}') })
        payload = { deleted: true, reason: '', history_id: 'h_abcdef123456', confirmId: 'c1' }
      } else if (method === 'GET' && path === '/api/history?limit=50') {
        payload = GROUPS
      } else if (method === 'GET' && path === '/api/browse/roots') {
        payload = ROOTS
      } else if (method === 'GET' && path.startsWith('/api/browse?path=')) {
        const dir = decodeURIComponent(path.split('path=')[1])
        payload =
          dir === '/media1/library'
            ? {
                path: dir,
                parent: null,
                root: dir,
                entries: [
                  { name: 'Other Show', path: '/media1/library/Other Show', isDir: true, videoCount: 3, seasonNumber: null },
                ],
              }
            : { path: dir, parent: '/media1/library', root: '/media1/library', entries: [] }
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
    })
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderPage() {
  return render(
    <AppStoreProvider>
      <HistoryPage />
    </AppStoreProvider>
  )
}

async function expandFirstCard() {
  renderPage()
  await screen.findByText('New Show')
  await userEvent.click(screen.getByText('New Show'))
  await screen.findByText('Source → Target Path')
}

describe('HistoryPage', () => {
  it('renders one card per Confirm with count and expand/collapse', async () => {
    await expandFirstCard()
    expect(screen.getAllByText(/2 files?/).length).toBeGreaterThan(0)
    expect(screen.getByText('h_abcdef'.slice(0, 6))).toBeTruthy()
    expect(screen.getByText('Save & Move Again')).toBeInTheDocument()
    expect(screen.getByText('Undo')).toBeInTheDocument()
  })

  it('shows Scan-report row parity: badges, PathPills, size, trail', async () => {
    await expandFirstCard()
    expect(screen.getByText('Suspect')).toBeInTheDocument()
    expect(screen.getByText('Cross-drive')).toBeInTheDocument()
    expect(screen.queryByText('Corrected')).not.toBeInTheDocument()
    // PathPills rendered for both rows
    const pills = document.querySelectorAll('.status-pill')
    expect(pills.length).toBeGreaterThanOrEqual(4)
    // size formatted for c1 only (c2 has null size)
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
    // trail now shows compact summary button, popup has full movement trail table
    const trailButtons = screen.getAllByRole('button', { name: /hop/ })
    expect(trailButtons.length).toBeGreaterThanOrEqual(1)
    expect(trailButtons[0]).toHaveTextContent(/1 hop/)
    await userEvent.click(trailButtons[0])
    expect(await screen.findByText('Full movement trail')).toBeInTheDocument()
    expect(screen.getAllByText('/media1/downloads/New.Show.S01E01.mkv').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('/media1/library/New Show/Season 01/New Show S01E01.mkv').length).toBeGreaterThanOrEqual(1)
    await userEvent.click(screen.getByText('Close'))
    // status badges
    expect(screen.getByText('moved')).toBeInTheDocument()
    expect(screen.getByText('replaced')).toBeInTheDocument()
  })

  it('shows Delete only when the source file still exists and calls delete-source', async () => {
    await expandFirstCard()
    expect(screen.getByText('Delete')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Delete'))
    await waitFor(() => expect(posted.some((p) => p.kind === 'delete-source' && p.body.confirmId === 'c1')).toBe(true))
  })

  it('edits a target and saves via Save & Move Again (retarget POST)', async () => {
    await expandFirstCard()
    const input = screen.getAllByPlaceholderText('New target path')[0]
    await userEvent.clear(input)
    await userEvent.type(input, '/media1/library/New Show/Season 02/New Show S01E01.mkv')
    await userEvent.click(screen.getByText('Save & Move Again'))
    await waitFor(() => expect(posted.some((p) => p.kind === 'retarget')).toBe(true))
    const call = posted.find((p) => p.kind === 'retarget')
    expect(call.body.updates).toEqual([
      { confirmId: 'c1', newTarget: '/media1/library/New Show/Season 02/New Show S01E01.mkv' },
    ])
  })

  it('Undo calls the undo endpoint', async () => {
    await expandFirstCard()
    await userEvent.click(screen.getByText('Undo'))
    await waitFor(() => expect(posted.some((p) => p.kind === 'undo')).toBe(true))
  })

  it('Browse… opens the folder picker and picking a folder fills the target input', async () => {
    await expandFirstCard()
    await userEvent.click(screen.getAllByText('Browse…')[0])
    expect(await screen.findByText('Choose target folder')).toBeInTheDocument()
    await userEvent.click(screen.getAllByText('/media1/library')[0])
    expect(await screen.findByText('Other Show')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Other Show'))
    await userEvent.click(screen.getByRole('button', { name: 'Select this folder' }))
    await waitFor(() => {
      const input = screen.getAllByPlaceholderText('New target path')[0]
      expect(input.value).toBe('/media1/library/Other Show')
    })
  })

  it('shows no summary pills, filter chips, or search bar', async () => {
    await expandFirstCard()
    expect(document.querySelector('.summary-strip')).toBeNull()
    expect(document.querySelector('.filter-chips')).toBeNull()
    expect(document.querySelector('.search-bar')).toBeNull()
  })

  it('shows the empty state when there are no confirms', async () => {
    window.fetch.mockImplementationOnce(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ groups: [] }) })
    )
    renderPage()
    expect(await screen.findByText(/No confirms yet/)).toBeInTheDocument()
    expect(screen.queryByText('Save & Move Again')).not.toBeInTheDocument()
  })
})
