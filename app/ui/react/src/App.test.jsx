import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App.jsx'
import { AppStoreProvider } from './store/AppStore.jsx'

function toolsList() {
  return { jsonrpc: '2.0', id: 1, result: { tools: [{ name: 'move new downloads scan' }] } }
}

function jsonRpcResult(payload) {
  return {
    jsonrpc: '2.0',
    id: 1,
    result: { content: [{ type: 'text', text: JSON.stringify(payload) }] },
  }
}

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

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((_url, opts) => {
      const body = opts?.body ? JSON.parse(opts.body) : null
      let payload
      if (body?.method === 'tools/list') {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(toolsList()) })
      }
      if (body?.method === 'tools/call' && body.params.name === 'get available jellyfin libraries list') {
        payload = { libraries: [{ name: 'Movies' }, { name: 'Series' }] }
      } else if (body?.method === 'tools/call' && body.params.name === 'get move new downloads scan report') {
        payload = REPORT
      } else {
        payload = {}
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(jsonRpcResult(payload)) })
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

describe('App integration', () => {
  it('connects, loads libraries and renders the full report', async () => {
    renderApp()

    expect(await screen.findByText('connected (1 tools)')).toBeInTheDocument()
    expect(screen.getByText('Scan Movies')).toBeInTheDocument()
    expect(screen.getByText('Scan Series')).toBeInTheDocument()

    expect((await screen.findAllByText('Show Name (2020)')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('Movie (2024)')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('Skipped items')).length).toBeGreaterThan(0)

    expect(screen.getByText('Actions Needed')).toBeInTheDocument()
    expect(screen.getByText(/scan_id: scan1/)).toBeInTheDocument()
    expect(screen.getAllByText('Cross-drive').length).toBeGreaterThan(0)
    expect(screen.getByText('S01E01')).toBeInTheDocument()

    expect(screen.getByLabelText(/^Show:/)).toHaveClass('missing')
    expect(screen.getAllByLabelText(/^File:/).some((el) => el.classList.contains('exists'))).toBe(true)

    expect(await screen.findByText('2 of 2 item(s) selected')).toBeInTheDocument()
  })

  it('filters rows via the search box', async () => {
    renderApp()
    await screen.findAllByText('Movie (2024)')

    await userEvent.type(screen.getByPlaceholderText('Search by title, path...'), 'Movie')

    const { waitFor } = await import('@testing-library/react')
    await waitFor(() => {
      expect(screen.queryByText('Show Name (2020)')).not.toBeInTheDocument()
    })
  })

  it('select mode buttons update the selection summary', async () => {
    renderApp()
    await screen.findAllByText('Movie (2024)')

    await userEvent.click(screen.getByText('Select all new'))

    // c1 is a move item -> only 1 selected after the mode button
    expect(await screen.findByText('1 of 2 item(s) selected')).toBeInTheDocument()
  })

  it('opens the confirm modal preflight when Confirm Selected is clicked', async () => {
    renderApp()
    await screen.findAllByText('Movie (2024)')
    await screen.findByText('2 of 2 item(s) selected')

    await userEvent.click(screen.getByText('Confirm Selected'))

    const modal = await screen.findByText('Start Move')
    expect(modal).toBeInTheDocument()
    expect(screen.getByText(/Confirm Move/)).toBeInTheDocument()
    expect(modal.closest('#confirmModal').querySelectorAll('.confirm-row').length).toBeGreaterThan(0)
  })
})
