import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import { AppStoreProvider } from '../store/AppStore.jsx'

const FS_ROOT = {
  path: '/',
  parent: null,
  entries: [
    { name: 'media1', path: '/media1' },
    { name: 'media2', path: '/media2' },
    { name: 'srv', path: '/srv' },
  ],
}
const FS_MEDIA1 = {
  path: '/media1',
  parent: '/',
  entries: [{ name: 'downloads', path: '/media1/downloads' }],
}

function fsPayloadFor(url) {
  const match = String(url).match(/path=([^&]+)/)
  const target = match ? decodeURIComponent(match[1]) : '/'
  if (target === '/') return FS_ROOT
  return FS_MEDIA1
}

function stubFetch(record) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url, opts) => {
      const method = (opts?.method || 'GET').toUpperCase()
      const path = String(url)
      if (record) record.push({ method, path, body: opts?.body })
      let payload = {}
      if (method === 'GET' && path === '/api/status') payload = { auth: { required: false }, roots_configured: false }
      else if (method === 'GET' && path === '/api/libraries') payload = { libraries: [] }
      else if (method === 'GET' && path.startsWith('/api/scans/history')) payload = { history: [] }
      else if (method === 'GET' && path.startsWith('/api/scans/current/report')) payload = { hint: 'no scan' }
      else if (method === 'GET' && path.startsWith('/api/setup/fs')) payload = fsPayloadFor(path)
      else if (method === 'POST' && path === '/api/admin/env') payload = { appliedLive: ['DOWNLOAD_ROOTS'], needsRecreate: [] }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
    })
  )
}

async function selectRow(name) {
  const row = screen.getByText(`${name}/`).closest('li')
  await userEvent.click(within(row).getByRole('button', { name: 'Select' }))
}

beforeEach(() => {
  window.history.pushState({}, '', '/')
  stubFetch(null)
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

describe('SetupWizard', () => {
  it('shows the wizard instead of the scan UI when roots are not configured', async () => {
    renderApp()
    expect(await screen.findByTestId('setup-wizard')).toBeInTheDocument()
    expect(screen.queryByText('Start Scan')).not.toBeInTheDocument()
    expect(screen.getAllByText('Downloads').length).toBeGreaterThan(0)
  })

  it('lets you browse into a folder, select it and advance steps', async () => {
    renderApp()
    await screen.findByTestId('setup-wizard')

    await userEvent.click(await screen.findByRole('button', { name: 'media1/' }))
    await screen.findByText('downloads/')
    await selectRow('downloads')
    expect(screen.getByRole('button', { name: 'Selected' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Pick your movies folders')).toBeInTheDocument()
  })

  it('skip setup returns to the normal UI without posting env changes', async () => {
    const calls = []
    stubFetch(calls)
    renderApp()
    await screen.findByTestId('setup-wizard')

    await userEvent.click(screen.getByRole('button', { name: 'Skip setup' }))

    await waitFor(() => expect(screen.getByText('Start Scan')).toBeInTheDocument())
    expect(calls.find((c) => c.method === 'POST')).toBeUndefined()
  })

  it('finish setup posts joined roots to the env endpoint', async () => {
    const calls = []
    stubFetch(calls)
    renderApp()
    await screen.findByTestId('setup-wizard')

    // Downloads step (root view -> navigate into media1)
    await userEvent.click(await screen.findByRole('button', { name: 'media1/' }))
    await screen.findByText('downloads/')
    await selectRow('downloads')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    // Movies step: FS_MEDIA1 has exactly one entry
    await screen.findByText('Pick your movies folders')
    await selectRow('downloads')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    // Series step
    await selectRow('downloads')
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    // Jellyfin step -> Review
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByRole('heading', { name: 'Review' })).toBeInTheDocument()
    expect(screen.getAllByText(/\/media1\/downloads/).length).toBeGreaterThan(0)

    await userEvent.click(screen.getByRole('button', { name: 'Finish setup' }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/api/admin/env')
      expect(post).toBeTruthy()
      const body = JSON.parse(post.body)
      expect(body.updates.DOWNLOAD_ROOTS).toBe('/media1/downloads')
      expect(body.updates.MOVIE_ROOTS).toBe('/media1/downloads')
      expect(body.updates.SERIES_ROOTS).toBe('/media1/downloads')
    })
  })
})
