import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import { AppStoreProvider } from '../store/AppStore.jsx'

const REPORT = {
  summary: { scan_id: 'scan1', movies: 0, series: 1, skipped: 0, action_required: 1 },
  items: [
    {
      confirmId: 'c1',
      action: 'move',
      itemType: 'series',
      sourcePath: '/media1/downloads/New.Show.S01E01.mkv',
      targetPath: '/media1/series/New Show (2025)/Season 01/New Show S01E01.mkv',
      pathExists: 'Show ✗, Season ✗, File ✗',
      fileExists: false,
      fileSize: 1024,
      crossDrive: false,
      suspect: true,
      flags: ['phantom_show_folder'],
    },
  ],
}

const ROOTS = {
  roots: [
    { key: 's1', path: '/media1/series', kind: 'series', description: 'Series library' },
    { key: 'm1', path: '/media1/movies', kind: 'movie', description: 'Movie library' },
  ],
}

let posted = []
let resolvePath = '/media1/series/New Show (2025)'

beforeEach(() => {
  posted = []
  resolvePath = '/media1/series/New Show (2025)'
  window.history.pushState({}, '', '/')
  vi.stubGlobal(
    'fetch',
    vi.fn((url, opts) => {
      const method = (opts?.method || 'GET').toUpperCase()
      const path = String(url)
      let payload = {}
      if (method === 'POST' && path === '/api/scans/current/items/retarget') {
        posted.push(JSON.parse(opts.body || '{}'))
        payload = REPORT
      } else if (method === 'GET' && path === '/api/status') {
        payload = { auth: { required: false } }
      } else if (method === 'GET' && path === '/api/libraries') {
        payload = { libraries: [] }
      } else if (method === 'GET' && path === '/api/scans/current/report') {
        payload = REPORT
      } else if (method === 'GET' && path === '/api/browse/roots') {
        payload = ROOTS
      } else if (method === 'GET' && path.startsWith('/api/browse/resolve?target=')) {
        payload = { path: resolvePath, target: decodeURIComponent(path.split('target=')[1]) }
      } else if (method === 'GET' && path.startsWith('/api/browse/search?q=')) {
        const q = decodeURIComponent(path.split('q=')[1])
        payload = {
          results:
            q === 'zzz'
              ? []
              : [
                  { name: 'Existing Show', path: '/media1/series/Existing Show', kind: 'series', seasonNumber: null },
                ],
        }
      } else if (method === 'GET' && path.startsWith('/api/browse?path=')) {
        const dir = decodeURIComponent(path.split('path=')[1])
        if (dir === '/media1/series') {
          payload = {
            path: '/media1/series',
            parent: null,
            root: '/media1/series',
            entries: [
              { name: 'Existing Show', path: '/media1/series/Existing Show', isDir: true, videoCount: 0, seasonNumber: null },
            ],
          }
        } else if (dir === '/media1/series/Existing Show') {
          payload = {
            path: '/media1/series/Existing Show',
            parent: '/media1/series',
            root: '/media1/series',
            entries: [
              { name: 'Season 05', path: '/media1/series/Existing Show/Season 05', isDir: true, videoCount: 12, seasonNumber: 5 },
            ],
          }
        } else if (dir === '/media1/series/New Show (2025)') {
          payload = {
            path: '/media1/series/New Show (2025)',
            parent: '/media1/series',
            root: '/media1/series',
            entries: [],
          }
        } else {
          payload = { path: dir, parent: null, root: '/media1/series', entries: [] }
        }
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
    })
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderApp() {
  return render(
    <AppStoreProvider>
      <App />
    </AppStoreProvider>
  )
}

describe('BrowseModal', () => {
  it('opens at the resolved target folder, climbs back to all libraries, then retargets', async () => {
    renderApp()

    expect(await screen.findAllByText('New Show (2025)')).toBeTruthy()
    expect(document.querySelector('.suspect-badge')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Browse/ }))

    expect(await screen.findByText('Choose target folder')).toBeInTheDocument()
    // Resolved open path (the existing show folder), not the roots list.
    expect(await screen.findByText(/Target: .*New Show \(2025\)/)).toBeInTheDocument()
    expect(screen.queryByText('/media1/movies')).not.toBeInTheDocument()
    // The All libraries crumb is present so climbing back works.
    await userEvent.click(screen.getByText('All libraries'))
    expect(screen.getAllByText('/media1/series').length).toBeGreaterThan(0)
    expect(screen.getAllByText('/media1/movies').length).toBeGreaterThan(0)

    await userEvent.click(screen.getAllByText('/media1/series')[0])
    expect(await screen.findByText('Existing Show')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Existing Show'))
    expect(await screen.findByText('Season 05')).toBeInTheDocument()
    expect(screen.getByText('S5')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Season 05'))
    expect(await screen.findByText(/Target: .*Season 05/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Select this folder' }))

    await waitFor(() => expect(posted.length).toBe(1))
    expect(posted[0].confirmId).toBe('c1')
    expect(posted[0].directory).toBe('/media1/series/Existing Show/Season 05')
    expect(posted[0].applyToGroup).toBe(false)
    expect(posted[0].reclassifyAsMovie).toBe(false)
  })

  it('falls back to all libraries when the target does not resolve', async () => {
    resolvePath = null
    renderApp()

    expect(await screen.findAllByText('New Show (2025)')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: /Browse/ }))

    expect(await screen.findByText('Choose target folder')).toBeInTheDocument()
    expect(screen.getAllByText('/media1/series').length).toBeGreaterThan(0)
    expect(screen.getAllByText('/media1/movies').length).toBeGreaterThan(0)
    expect(screen.queryByText('All libraries')).not.toBeInTheDocument()
  })

  it('searches across all libraries and retargets to a hit root', async () => {
    renderApp()
    await screen.findAllByText('New Show (2025)')

    await userEvent.click(screen.getByRole('button', { name: /Browse/ }))
    await screen.findByText('Choose target folder')

    await userEvent.type(screen.getByPlaceholderText(/search existing folders/i), 'existing')
    expect(screen.queryAllByText('Existing Show')).toHaveLength(0)
    await userEvent.keyboard('{Enter}')
    const hit = (await screen.findAllByText('Existing Show')).find(
      (el) => el.closest('.search-hit')
    )
    await userEvent.click(hit)
    expect(await screen.findByText('Season 05')).toBeInTheDocument()
  })

  it('shows a message when the search finds no folders', async () => {
    renderApp()
    await screen.findAllByText('New Show (2025)')

    await userEvent.click(screen.getByRole('button', { name: /Browse/ }))
    await screen.findByText('Choose target folder')

    await userEvent.type(screen.getByPlaceholderText(/search existing folders/i), 'zzz')
    await userEvent.keyboard('{Enter}')

    expect(await screen.findByText(/No folders match/)).toBeInTheDocument()
    expect(screen.queryByText('All libraries')).not.toBeInTheDocument()
  })
})
