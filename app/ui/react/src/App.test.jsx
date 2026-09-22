import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App.jsx'
import { AppStoreProvider } from './store/AppStore.jsx'

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
  window.history.pushState({}, '', '/')
  try {
    localStorage.removeItem('jsort_transfer_active')
  } catch {}
  vi.stubGlobal(
    'fetch',
    vi.fn((url, opts) => {
      const method = (opts?.method || 'GET').toUpperCase()
      const path = String(url)
      let payload = {}
      if (method === 'GET' && path === '/api/status') {
        payload = { auth: { required: false } }
      } else if (method === 'GET' && path === '/api/libraries') {
        payload = { libraries: [{ name: 'Movies' }, { name: 'Series' }] }
      } else if (method === 'GET' && (path === '/api/scans/current/report' || path === '/api/scans/scan1/report')) {
        payload = REPORT
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

describe('App integration', () => {
  it('connects, loads libraries and renders the full report', async () => {
    renderApp()

    expect(await screen.findByText(/Move your new files to the dedicated library folders/)).toBeInTheDocument()
    expect(screen.getByText('Scan library...')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Scan library...'))
    expect(await screen.findByText('Scan Movies')).toBeInTheDocument()
    expect(screen.getByText('Scan Series')).toBeInTheDocument()

    expect((await screen.findAllByText('Show Name (2020)')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('Movie (2024)')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('Skipped items')).length).toBeGreaterThan(0)

    expect(screen.getByText('Actions Needed')).toBeInTheDocument()
    // scan_id no longer shown in the report header (removed per user request)
    expect(screen.queryByText(/scan_id: scan1/)).not.toBeInTheDocument()
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

  it('selection summary updates when an item is toggled', async () => {
    renderApp()
    await screen.findAllByText('Movie (2024)')
    expect(await screen.findByText('2 of 2 item(s) selected')).toBeInTheDocument()
    // Click the first actionable item checkbox (skip the Skipped group's item)
    const actionableChecks = document.querySelectorAll('.item-check:not(.skip-check)')
    expect(actionableChecks.length).toBe(2)
    await userEvent.click(actionableChecks[0])
    expect(await screen.findByText('1 of 2 item(s) selected')).toBeInTheDocument()
  })

  it('opens the confirm modal preflight when a group Confirm is clicked', async () => {
    renderApp()
    await screen.findAllByText('Movie (2024)')
    await screen.findByText('2 of 2 item(s) selected')

    await userEvent.click(screen.getAllByText('Confirm')[0])

    const modal = await screen.findByText('Start Move')
    expect(modal).toBeInTheDocument()
    expect(screen.getByText(/Confirm Move/)).toBeInTheDocument()
    expect(modal.closest('#confirmModal').querySelectorAll('.confirm-row').length).toBeGreaterThan(0)
  })

  it('hides the group Confirm while a path is edited and restores it after Update Paths', async () => {
    renderApp()
    await screen.findAllByText('Movie (2024)')

    expect(screen.getAllByText('Confirm').length).toBe(2)

    const input = screen.getByDisplayValue('/media1/series/Show Name (2020)/Season 01/Show Name S01E01.mkv')
    await userEvent.clear(input)
    await userEvent.type(input, '/media1/series/Show Name (2020)/Season 01/Show Name S01E01v2.mkv')

    expect(screen.getAllByText('Confirm').length).toBe(1)
    const updatePaths = screen.getByText('Update Paths')
    expect(updatePaths).toBeInTheDocument()

    await userEvent.click(updatePaths)

    expect((await screen.findAllByText('Confirm')).length).toBe(2)
    expect(screen.queryByText('Update Paths')).not.toBeInTheDocument()
  })

  it('does not flash the Start Scan button between scan completion and report load', async () => {
    let reportCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') {
          payload = { auth: { required: false } }
        } else if (method === 'GET' && path === '/api/libraries') {
          payload = { libraries: [] }
        } else if (method === 'GET' && path.includes('/api/scans/') && path.includes('/report')) {
          reportCalls += 1
          payload = reportCalls === 1 ? { hint: 'no scan' } : REPORT
        } else if (method === 'POST' && path === '/api/scans') {
          payload = { scan_id: 's9', processed: 0, total: 10, percent: 0, status: 'starting' }
        } else if (method === 'GET' && path.includes('/api/scans/') && path.includes('/progress')) {
          payload = { scan_id: 's9', status: 'completed', processed: 10, total: 10, percent: 100 }
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()

    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByText('Start Scan'))

    expect(await screen.findByText('Loading report...', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText('Start Scan')).not.toBeInTheDocument()

    expect((await screen.findAllByText('Movie (2024)', {}, { timeout: 3000 })).length).toBeGreaterThan(0)
    expect(screen.queryByText('Loading report...')).not.toBeInTheDocument()
  })

  it('queues a confirm batch instead of blocking when a move is already running', async () => {
    let confirmPosts = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') {
          payload = { auth: { required: false } }
        } else if (method === 'GET' && path === '/api/libraries') {
          payload = { libraries: [] }
        } else if (method === 'GET' && path === '/api/scans/current/report') {
          payload = REPORT
        } else if (method === 'POST' && path === '/api/scans/current/confirm') {
          confirmPosts += 1
          payload = {
            scan_id: 'scan1',
            status: 'running',
            processed: 1,
            total: 4,
            queue_length: confirmPosts,
            queue_items: 2,
            counts: { moved: 1, replaced: 0, failed: 0 },
          }
        } else if (method === 'GET' && path === '/api/scans/current/confirm-progress') {
          payload = {
            scan_id: 'scan1',
            status: 'running',
            processed: 1,
            total: 4,
            queue_length: confirmPosts,
            queue_items: 2,
            counts: { moved: 1, replaced: 0, failed: 0 },
            current_file: '/media1/downloads/Show.S01E01.mkv',
          }
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findAllByText('Movie (2024)')

    // First batch: queued behind the running move instead of being blocked.
    await userEvent.click(screen.getAllByText('Confirm')[0])
    await userEvent.click(await screen.findByText('Start Move'))
    expect(await screen.findByText('Added to queue — will start after the current move finishes')).toBeInTheDocument()

    // A second batch: the modal warns it will be queued, and Start Move queues it too.
    await userEvent.click(screen.getAllByText('Confirm')[1])
    expect(await screen.findByText('A move is already running')).toBeInTheDocument()
    expect(screen.getByText(/will be added to the queue/)).toBeInTheDocument()

    await userEvent.click(screen.getByText('Start Move'))
    const queuedToasts = await screen.findAllByText('Added to queue — will start after the current move finishes')
    expect(queuedToasts.length).toBeGreaterThanOrEqual(2)
    expect(confirmPosts).toBe(2)
  })

  it('starts polling confirm progress and closes the transfer toast when the move completes', async () => {
    let confirmPosts = 0
    let progressGets = 0
    let done = false
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') {
          payload = { auth: { required: false } }
        } else if (method === 'GET' && path === '/api/libraries') {
          payload = { libraries: [] }
        } else if (method === 'GET' && path === '/api/scans/current/report') {
          payload = REPORT
        } else if (method === 'POST' && path === '/api/scans/current/confirm') {
          confirmPosts += 1
          payload = { scan_id: 'scan1', status: 'running', processed: 0, total: 1, queue_length: 0 }
        } else if (method === 'GET' && path === '/api/scans/current/confirm-progress') {
          progressGets += 1
          if (progressGets >= 2) done = true
          payload = done
            ? {
                scan_id: 'scan1',
                status: 'completed',
                processed: 1,
                total: 1,
                queue_length: 0,
                counts: { moved: 1, replaced: 0, failed: 0 },
              }
            : { scan_id: 'scan1', status: 'running', processed: 1, total: 1, queue_length: 0 }
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findAllByText('Movie (2024)')

    await userEvent.click(screen.getAllByText('Confirm')[0])
    await userEvent.click(await screen.findByText('Start Move'))
    expect(await screen.findByText('Confirm started in background')).toBeInTheDocument()

    expect(await screen.findByText(/Confirm completed! Moved: 1/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(progressGets).toBeGreaterThanOrEqual(2)
    expect(confirmPosts).toBe(1)
  })

  it('consumes confirm progress from the SSE stream when EventSource is available', async () => {
    class FakeEventSource {
      constructor(url) {
        FakeEventSource.instances.push(this)
        this.url = url
        this.closed = false
      }
      close() {
        this.closed = true
      }
      emit(data) {
        this.onmessage({ data: JSON.stringify(data) })
      }
    }
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)

    let confirmProgressGets = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') {
          payload = { auth: { required: false } }
        } else if (method === 'GET' && path === '/api/libraries') {
          payload = { libraries: [] }
        } else if (method === 'GET' && path === '/api/scans/current/report') {
          payload = REPORT
        } else if (method === 'POST' && path === '/api/scans/current/confirm') {
          payload = { scan_id: 'scan1', status: 'running', processed: 0, total: 1, queue_length: 0 }
        } else if (method === 'GET' && path === '/api/scans/current/confirm-progress') {
          confirmProgressGets += 1
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findAllByText('Movie (2024)')

    await userEvent.click(screen.getAllByText('Confirm')[0])
    await userEvent.click(await screen.findByText('Start Move'))
    expect(await screen.findByText('Confirm started in background')).toBeInTheDocument()

    const es = FakeEventSource.instances[0]
    expect(es).toBeTruthy()
    expect(es.url).toContain('/api/scans/confirm/events')

    es.emit({ scan_id: 'scan1', status: 'running', processed: 1, total: 1, queue_length: 0 })
    es.emit({
      scan_id: 'scan1',
      status: 'completed',
      processed: 1,
      total: 1,
      queue_length: 0,
      counts: { moved: 1, replaced: 0, failed: 0 },
    })

    expect(await screen.findByText(/Confirm completed! Moved: 1/)).toBeInTheDocument()
    expect(es.closed).toBe(true)
    expect(confirmProgressGets).toBe(0)
  })

  it('shows scan progress after page load when a scan is already running', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') {
          payload = { auth: { required: false } }
        } else if (method === 'GET' && path === '/api/libraries') {
          payload = { libraries: [] }
        } else if (method === 'GET' && path === '/api/scans/current/report') {
          payload = {
            summary: { scan_id: 's1', status: 'running' },
            progress: {
              scan_id: 's1',
              status: 'running',
              processed: 3,
              total: 10,
              percent: 30,
              current_file: '/media1/downloads/Show.mkv',
            },
          }
        } else if (method === 'GET' && path === '/api/scans/current/progress') {
          payload = {
            scan_id: 's1',
            status: 'running',
            processed: 3,
            total: 10,
            percent: 30,
            current_file: '/media1/downloads/Show.mkv',
          }
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()

    expect(await screen.findByText('Scanning...', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('30%')).toBeInTheDocument()
    expect(screen.getByText('3/10')).toBeInTheDocument()
    expect(screen.getByText('/media1/downloads/Show.mkv')).toBeInTheDocument()
    expect(screen.queryByText('Start Scan')).not.toBeInTheDocument()
  })

  it('keeps Start Scan visible when logs are shown and no report exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') {
          payload = { auth: { required: false } }
        } else if (method === 'GET' && path === '/api/libraries') {
          payload = { libraries: [] }
        } else if (method === 'GET' && path.includes('/report')) {
          payload = { hint: 'no scan' }
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()

    await screen.findByText('Start Scan')
    expect(screen.queryByText('Show Logs')).not.toBeInTheDocument()
    expect(screen.queryByText('Hide Logs')).not.toBeInTheDocument()
    expect(screen.getByText('Start Scan')).toBeInTheDocument()
  })

  it('shows the login screen when auth is required and unlocks after login', async () => {
    let statusCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (path === '/api/status') {
          statusCalls += 1
          payload = statusCalls === 1 ? { auth: { required: true } } : { auth: { required: false } }
        } else if (method === 'POST' && path === '/api/login') {
          payload = { token: 'tok123', directLogin: true }
        } else if (method === 'GET' && path === '/api/libraries') {
          payload = { libraries: [] }
        } else if (method === 'GET' && path === '/api/scans/current/report') {
          payload = { hint: 'no scan' }
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()

    expect(await screen.findByPlaceholderText('Panel password')).toBeInTheDocument()
    expect(screen.queryByText('Start Scan')).not.toBeInTheDocument()

    await userEvent.type(screen.getByPlaceholderText('Panel password'), 'secret')
    await userEvent.click(screen.getByText('Log in'))

    expect(await screen.findByText('Start Scan')).toBeInTheDocument()
    expect(await screen.findByText('Logout')).toBeInTheDocument()
  })
})
