import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App.jsx'
import { AppStoreProvider } from './store/AppStore.jsx'

const ENV = {
  spec: [
    { key: 'MODEL_CLASSIFY_CONFIDENCE_THRESHOLD', section: 'ai', type: 'float', secret: false, apply: 'restart', description: 'Classification threshold', saved: '0.65', effective: '0.65' },
    { key: 'QBT_MCP_API_KEY', section: 'download', type: 'str', secret: true, apply: 'live', description: 'qBittorrent MCP key', saved: '********', effective: '********' },
    { key: 'JELLYSORT_MCP_TOKEN', section: 'mcp', type: 'str', secret: true, apply: 'live', description: 'JellySort MCP token', saved: '', effective: '' },
  ],
  saved: { MODEL_CLASSIFY_CONFIDENCE_THRESHOLD: '0.65', QBT_MCP_API_KEY: '********', JELLYSORT_MCP_TOKEN: '' },
  effective: { MODEL_CLASSIFY_CONFIDENCE_THRESHOLD: '0.65', QBT_MCP_API_KEY: '********', JELLYSORT_MCP_TOKEN: '' },
  pending: [],
}

beforeEach(() => {
  window.history.pushState({}, '', '/')
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
        payload = { hint: 'no scan' }
      } else if (method === 'GET' && path === '/api/admin/env') {
        payload = ENV
      } else if (method === 'POST' && path === '/api/admin/env') {
        payload = { appliedLive: ['JELLYSORT_MCP_TOKEN'], needsRecreate: [] }
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

describe('page navigation', () => {
  it('renders header buttons and switches to the Settings page', async () => {
    renderApp()
    await screen.findByText('Start Scan')

    expect(screen.getByRole('button', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'History' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show Logs' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Hide Logs' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))

    expect(await screen.findByText(/Environment variables read from \.env\./)).toBeInTheDocument()
    expect(screen.getByText('Classification')).toBeInTheDocument()
    expect(screen.queryByText('Start Scan')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toHaveClass('active')

    await userEvent.click(screen.getByTitle('Go to homepage'))

    expect(await screen.findByText('Start Scan')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).not.toHaveClass('active')
  })

  it('restores the page from the URL path on load', async () => {
    window.history.pushState({}, '', '/settings')
    renderApp()

    expect(await screen.findByText(/Environment variables read from \.env\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toHaveClass('active')
  })

  it('updates the URL when navigating', async () => {
    renderApp()
    await screen.findByText('Start Scan')

    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('MCP Access Control')
    expect(window.location.pathname).toBe('/settings')

    await userEvent.click(screen.getByTitle('Go to homepage'))
    await screen.findByText('Start Scan')
    expect(window.location.pathname).toBe('/')
  })
})

describe('Settings page', () => {
  it('shows live/recreate badges and masks secrets', async () => {
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))

    await screen.findByText('Classification')
    expect(screen.getByLabelText('MODEL_CLASSIFY_CONFIDENCE_THRESHOLD')).toHaveValue('0.65')
    expect(screen.getByLabelText('QBT_MCP_API_KEY')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('QBT_MCP_API_KEY')).toHaveValue('')
    expect(screen.getAllByText('recreate').length).toBeGreaterThan(0)
    expect(screen.getAllByText('live').length).toBeGreaterThan(0)
  })

  it('disables the save button when nothing changed', async () => {
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('Classification')

    expect(screen.getByRole('button', { name: /Save Changes/ })).toBeDisabled()
  })

  it('posts only changed values and reloads', async () => {
    const calls = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        calls.push({ method, path, body: opts?.body })
        let payload = {}
        if (method === 'GET' && path === '/api/status') payload = { auth: { required: false } }
        else if (method === 'GET' && path === '/api/libraries') payload = { libraries: [] }
        else if (method === 'GET' && path === '/api/scans/current/report') payload = { hint: 'no scan' }
        else if (method === 'GET' && path === '/api/admin/env') payload = ENV
        else if (method === 'POST' && path === '/api/admin/env') payload = { appliedLive: ['MODEL_CLASSIFY_CONFIDENCE_THRESHOLD'], needsRecreate: ['MODEL_CLASSIFY_CONFIDENCE_THRESHOLD'] }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('Classification')

    await userEvent.clear(screen.getByLabelText('MODEL_CLASSIFY_CONFIDENCE_THRESHOLD'))
    await userEvent.type(screen.getByLabelText('MODEL_CLASSIFY_CONFIDENCE_THRESHOLD'), '0.7')

    const save = screen.getByRole('button', { name: /Save Changes/ })
    expect(save).not.toBeDisabled()
    await userEvent.click(save)

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/api/admin/env')
      expect(post).toBeTruthy()
      expect(JSON.parse(post.body)).toEqual({ updates: { MODEL_CLASSIFY_CONFIDENCE_THRESHOLD: '0.7' } })
    })
  })

  it('shows an inline error and blocks save for invalid numeric values', async () => {
    const calls = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        calls.push({ method, path })
        let payload = {}
        if (method === 'GET' && path === '/api/status') payload = { auth: { required: false } }
        else if (method === 'GET' && path === '/api/libraries') payload = { libraries: [] }
        else if (method === 'GET' && path === '/api/scans/current/report') payload = { hint: 'no scan' }
        else if (method === 'GET' && path === '/api/admin/env') payload = ENV
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('Classification')

    const field = screen.getByLabelText('MODEL_CLASSIFY_CONFIDENCE_THRESHOLD')
    expect(field).toHaveAttribute('type', 'text')
    await userEvent.clear(field)
    await userEvent.type(field, 'abc')

    expect(await screen.findByText('Must be a number')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Save Changes/ }))
    expect(await screen.findByText(/Fix invalid values before saving/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')).toBeUndefined()
  })

  it('toasts applied-live for live-only saves', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') payload = { auth: { required: false } }
        else if (method === 'GET' && path === '/api/libraries') payload = { libraries: [] }
        else if (method === 'GET' && path === '/api/scans/current/report') payload = { hint: 'no scan' }
        else if (method === 'GET' && path === '/api/admin/env') payload = ENV
        else if (method === 'POST' && path === '/api/admin/env') payload = { appliedLive: ['JELLYSORT_MCP_TOKEN'], needsRecreate: [] }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('MCP Access Control')

    const field = screen.getByLabelText('JELLYSORT_MCP_TOKEN')
    await userEvent.type(field, 'newtoken123')

    await userEvent.click(screen.getByRole('button', { name: /Save Changes/ }))

    expect(await screen.findByText(/applied live/)).toBeInTheDocument()
    expect(screen.queryByText(/Recreate required/)).not.toBeInTheDocument()
  })

  it('shows the recreate banner with a copy button for restart-var saves', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        let payload = {}
        if (method === 'GET' && path === '/api/status') payload = { auth: { required: false } }
        else if (method === 'GET' && path === '/api/libraries') payload = { libraries: [] }
        else if (method === 'GET' && path === '/api/scans/current/report') payload = { hint: 'no scan' }
        else if (method === 'GET' && path === '/api/admin/env') payload = ENV
        else if (method === 'POST' && path === '/api/admin/env') payload = { appliedLive: [], needsRecreate: ['MODEL_CLASSIFY_CONFIDENCE_THRESHOLD'] }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('Classification')

    const field = screen.getByLabelText('MODEL_CLASSIFY_CONFIDENCE_THRESHOLD')
    await userEvent.clear(field)
    await userEvent.type(field, '0.8')

    await userEvent.click(screen.getByRole('button', { name: /Save Changes/ }))

    expect(await screen.findByText(/Recreate required/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy command' })).toBeInTheDocument()
    expect(await screen.findByText(/Saved — 1 change need/)).toBeInTheDocument()
  })

  it('toggles the live/recreate/pending help box', async () => {
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('Classification')

    expect(screen.queryByText(/baked into config snapshots/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '?' }))
    expect(screen.getByText(/baked into config snapshots/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '?' }))
    expect(screen.queryByText(/baked into config snapshots/)).not.toBeInTheDocument()
  })
})
