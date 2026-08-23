import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import { AppStoreProvider } from '../store/AppStore.jsx'

const HISTORY = {
  history: [
    {
      scan_id: 'hist1',
      saved_at: new Date().toISOString(),
      movies: 1,
      series: 0,
      skipped: 0,
      action_required: 0,
      moved: 2,
      replaced: 0,
      failed: 0,
    },
  ],
}

function renderApp() {
  return render(
    <AppStoreProvider>
      <App />
    </AppStoreProvider>
  )
}

describe('Dashboard undo', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function stubFetch(undoPayloads) {
    const calls = []
    let undoCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const method = (opts?.method || 'GET').toUpperCase()
        const path = String(url)
        calls.push({ method, path })
        let payload = {}
        if (path === '/api/status') payload = { auth: { required: false }, roots_configured: true }
        else if (path === '/api/libraries') payload = { libraries: [] }
        else if (path === '/api/scans/current/report') payload = { hint: 'No scan found' }
        else if (path.startsWith('/api/scans/history')) payload = HISTORY
        else if (method === 'POST' && path === '/api/scans/hist1/undo') {
          payload = undoPayloads[Math.min(undoCount++, undoPayloads.length - 1)]
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) })
      })
    )
    return calls
  }

  it('shows an undo button for history entries with moves, calls the endpoint and reports empty undos', async () => {
    stubFetch([
      { ok: true, restored_count: 2, restored: [], skipped: [], missing: 0 },
      { ok: true, restored_count: 0, restored: [], skipped: [{ path: '/x', reason: 'target missing' }], missing: 1 },
    ])
    renderApp()

    const btn = await screen.findByRole('button', { name: 'Undo 2 moves' })
    await userEvent.click(btn)
    await screen.findByText(/Undone: 2 files moved back/)

    const btn2 = await screen.findByRole('button', { name: 'Undo 2 moves' })
    await userEvent.click(btn2)
    await screen.findByText(/Nothing to undo/)
  })
})
