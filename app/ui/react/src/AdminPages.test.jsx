import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App.jsx'
import { AppStoreProvider } from './store/AppStore.jsx'

const ENV = {
  spec: [
    { key: 'MODEL_CLASSIFY_CONFIDENCE_THRESHOLD', section: 'ai', type: 'float', secret: false, apply: 'restart', description: 'Classification threshold', saved: '0.65', effective: '0.65' },
    { key: 'QBT_MCP_API_KEY', section: 'download', type: 'str', secret: true, apply: 'live', description: 'qBittorrent MCP key', saved: '********', effective: '********' },
    { key: 'MCP_ALLOW_UNAUTHENTICATED', section: 'mcp', type: 'bool', secret: false, apply: 'live', description: 'Allow open MCP', saved: 'true', effective: 'true' },
  ],
  saved: { MODEL_CLASSIFY_CONFIDENCE_THRESHOLD: '0.65', QBT_MCP_API_KEY: '********', MCP_ALLOW_UNAUTHENTICATED: 'true' },
  effective: { MODEL_CLASSIFY_CONFIDENCE_THRESHOLD: '0.65', QBT_MCP_API_KEY: '********', MCP_ALLOW_UNAUTHENTICATED: 'true' },
  pending: [],
}

const KEYS = {
  keys: [
    {
      id: 'k_abc123',
      name: 'laptop agent',
      user: 'default',
      key_prefix: 'jsort_abc123',
      key_suffix: '9f2e',
      scopes: ['*'],
      enabled: true,
      created_at: '2026-08-01T10:00:00+00:00',
      last_used_at: null,
    },
    {
      id: 'k_def456',
      name: 'server agent',
      user: 'default',
      key_prefix: 'jsort_def456',
      key_suffix: '77aa',
      scopes: ['*'],
      enabled: true,
      created_at: '2026-07-15T09:30:00+00:00',
      last_used_at: '2026-08-10T22:11:00+00:00',
    },
  ],
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
      } else if (method === 'GET' && path === '/api/admin/api-keys') {
        payload = KEYS
      } else if (method === 'POST' && path === '/api/admin/api-keys') {
        payload = { ...KEYS.keys[0], id: 'k_new1', name: 'new key', key: 'jsort_newfullkey123456' }
      } else if (method === 'POST' && path === '/api/admin/env') {
        payload = { appliedLive: ['MCP_ALLOW_UNAUTHENTICATED'], needsRecreate: [] }
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
    expect(screen.getByRole('button', { name: 'API Keys' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show Logs' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))

    expect(await screen.findByText(/Environment variables read from \.env\./)).toBeInTheDocument()
    expect(screen.getByText('Classification')).toBeInTheDocument()
    expect(screen.queryByText('Start Scan')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).toHaveClass('active')

    await userEvent.click(screen.getByTitle('Go to homepage'))

    expect(await screen.findByText('Start Scan')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Settings' })).not.toHaveClass('active')
  })

  it('renders the API Keys page', async () => {
    renderApp()
    await screen.findByText('Start Scan')

    await userEvent.click(screen.getByRole('button', { name: 'API Keys' }))

    expect(await screen.findByText('laptop agent')).toBeInTheDocument()
    expect(screen.getByText('server agent')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Key' })).toBeInTheDocument()

    expect(screen.getByText((content) => content.includes('jsort_abc123') && content.includes('9f2e'))).toBeInTheDocument()
    expect(screen.getByText((content) => content.includes('jsort_def456') && content.includes('77aa'))).toBeInTheDocument()
    expect(screen.getByText('Never used')).toBeInTheDocument()
    expect(screen.getByText(/Last used/)).toBeInTheDocument()
    // Table header + 2 rows contain "Created", so check rows via table
    expect(screen.getAllByRole('row').length).toBe(3) // header + 2 data rows
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

    await userEvent.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('laptop agent')
    expect(window.location.pathname).toBe('/apikeys')

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
        else if (method === 'POST' && path === '/api/admin/env') payload = { appliedLive: ['MCP_ALLOW_UNAUTHENTICATED'], needsRecreate: [] }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await screen.findByText('MCP Access Control')

    const box = screen.getByLabelText('MCP_ALLOW_UNAUTHENTICATED')
    await userEvent.click(box) // true -> false

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

describe('API Keys page', () => {
  it('creates a key and shows the one-time full key', async () => {
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('laptop agent')

    await userEvent.click(screen.getByRole('button', { name: 'Create Key' }))
    await userEvent.type(screen.getByLabelText('Key name'), 'new key')
    await userEvent.click(screen.getByRole('button', { name: 'Create' }))

    expect(await screen.findByText('Key created — store it now')).toBeInTheDocument()
    expect(screen.getByText('jsort_newfullkey123456')).toBeInTheDocument()
  })

  it('requires a name before creating', async () => {
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('laptop agent')

    await userEvent.click(screen.getByRole('button', { name: 'Create Key' }))
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled()
  })

  it('deletes a key after confirmation', async () => {
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('laptop agent')

    vi.spyOn(window, 'confirm').mockImplementation(() => true)
    await userEvent.click(screen.getAllByRole('button', { name: 'Delete' })[0])

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled()
    })
  })

  it('samples the client setup help', async () => {
    renderApp()
    await screen.findByText('Start Scan')
    await userEvent.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('laptop agent')

    expect(screen.getByText('Client setup')).toBeInTheDocument()
    expect(within(screen.getByText('Client setup').closest('.panel')).getByText(/Authorization: Bearer/)).toBeInTheDocument()
  })
})
