import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Toasts from './Toasts.jsx'

let mockStore
let mockActions

vi.mock('../store/AppStore.jsx', () => ({
  useAppStore: () => ({ state: mockStore, actions: mockActions }),
}))

const QUEUE = [
  {
    id: 'transfer-a',
    order: 0,
    confirmId: 'a',
    group: 'Show Name',
    kind: 'series',
    batch: 'running',
    sourcePath: '/media1/d/alpha.mkv',
    name: 'alpha.mkv',
    state: 'done',
    progress: null,
    doneAt: 1000,
  },
  {
    id: 'transfer-b',
    order: 1,
    confirmId: 'b',
    group: 'Show Name',
    kind: 'series',
    batch: 'running',
    sourcePath: '/media1/d/beta.mkv',
    name: 'beta.mkv',
    state: 'copying',
    progress: {
      percent: 60,
      speed: '21.5 MB/s',
      eta: '1m 17s',
      copied: 2500000000,
      size: 4400000000,
    },
    doneAt: null,
  },
  {
    id: 'transfer-c',
    order: 2,
    confirmId: 'c',
    group: 'Movie',
    kind: 'movie',
    batch: 'queued',
    sourcePath: '/media1/d/gamma.mkv',
    name: 'gamma.mkv',
    state: 'queued',
    progress: null,
    doneAt: null,
  },
]

const SUMMARY = {
  processed: 1,
  total: 3,
  status: 'running',
  counts: { moved: 1, replaced: 0, failed: 0 },
}

beforeEach(() => {
  mockActions = { setTransferMinimized: vi.fn(), dismissTransfer: vi.fn(), dismissToast: vi.fn() }
  mockStore = { toasts: [], transferQueue: [], transferSummary: null, transferMinimized: false }
})

describe('Toasts transfer panel', () => {
  it('renders nothing when the queue is empty', () => {
    const { container } = render(<Toasts />)
    expect(container.querySelector('.transfer-toasts')).toBeNull()
  })

  it('keeps the completed header mounted after the rows fade', () => {
    mockStore = {
      ...mockStore,
      transferQueue: [],
      transferSummary: { processed: 3, total: 3, status: 'completed', counts: { moved: 3, replaced: 0, failed: 0 } },
    }
    const { container } = render(<Toasts />)
    expect(screen.getByText('Move completed')).toBeInTheDocument()
    expect(screen.getByText('Moved: 3 · Replaced: 0 · Failed: 0')).toBeInTheDocument()
    expect(container.querySelector('.transfer-panel')).toBeTruthy()
    // Dismiss is still offered with no rows left
    expect(screen.getByLabelText('Dismiss transfer panel')).toBeInTheDocument()
  })

  it('renders one persistent panel grouped by show/movie with live copy stats', () => {
    mockStore = { ...mockStore, transferQueue: QUEUE, transferSummary: SUMMARY }
    const { container } = render(<Toasts />)

    expect(screen.getByText('Moving 1 of 3')).toBeInTheDocument()
    // Single panel, sections carry the group names + counts
    expect(container.querySelectorAll('.transfer-panel')).toHaveLength(1)
    expect(screen.getByText('Show Name')).toBeInTheDocument()
    expect(screen.getByText('Movie')).toBeInTheDocument()
    // Queued batch section is badged
    expect(screen.getByText('Queued')).toBeInTheDocument()
    // Every row is listed (scrollable list, no cap)
    expect(screen.getByText('alpha.mkv')).toBeInTheDocument()
    expect(screen.getByText('beta.mkv')).toBeInTheDocument()
    expect(screen.getByText('gamma.mkv')).toBeInTheDocument()

    expect(screen.getByText('Moved: 1 · Replaced: 0 · Failed: 0')).toBeInTheDocument()
    expect(screen.getByText('2.3 GB / 4.1 GB')).toBeInTheDocument()
    expect(screen.getByText('21.5 MB/s')).toBeInTheDocument()
    expect(screen.getByText('ETA 1m 17s')).toBeInTheDocument()

    const copyingRow = container.querySelector('.transfer-row.copying')
    expect(copyingRow.querySelector('.transfer-spinner')).toBeTruthy()
    expect(copyingRow.querySelector('.transfer-progress .fill.file').style.width).toBe('60%')
    const doneRow = container.querySelector('.transfer-row.done')
    expect(doneRow.querySelector('.transfer-tick')).toBeTruthy()
  })

  it('shows the queued-batch count while a move is running', () => {
    mockStore = {
      ...mockStore,
      transferQueue: QUEUE,
      transferSummary: { ...SUMMARY, queueLength: 2, queueItems: 5 },
    }
    render(<Toasts />)
    expect(screen.getByText(/2 batches queued/)).toBeInTheDocument()
    expect(screen.queryByText(/1 batch queued/)).not.toBeInTheDocument()
  })

  it('uses singular wording for a single queued batch', () => {
    mockStore = {
      ...mockStore,
      transferQueue: QUEUE,
      transferSummary: { ...SUMMARY, queueLength: 1, queueItems: 2 },
    }
    render(<Toasts />)
    expect(screen.getByText(/1 batch queued/)).toBeInTheDocument()
  })

  it('shows the next queued file as up next before the copy starts', () => {
    const queuedOnly = QUEUE.map((t) => ({ ...t, state: 'queued', progress: null }))
    mockStore = {
      ...mockStore,
      transferQueue: queuedOnly,
      transferSummary: { ...SUMMARY, processed: 0 },
    }
    render(<Toasts />)
    expect(screen.getByText('Up next')).toBeInTheDocument()
    expect(screen.getByText('alpha.mkv')).toBeInTheDocument()
  })

  it('minimizes to a strip and expands again', () => {
    mockStore = { ...mockStore, transferQueue: QUEUE, transferSummary: SUMMARY }
    const { rerender } = render(<Toasts />)

    fireEvent.click(screen.getByLabelText('Minimize transfer panel'))
    expect(mockActions.setTransferMinimized).toHaveBeenCalledWith(true)

    mockStore = { ...mockStore, transferMinimized: true }
    rerender(<Toasts />)
    expect(screen.getByLabelText('Expand transfer panel')).toBeInTheDocument()
    // Minimized strip keeps the title but hides the rows
    expect(screen.getByText('Moving 1 of 3')).toBeInTheDocument()
    expect(screen.queryByText('beta.mkv')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Expand transfer panel'))
    expect(mockActions.setTransferMinimized).toHaveBeenCalledWith(false)
  })

  it('shows a completed header with dismiss and no minimize-only exit', () => {
    mockStore = {
      ...mockStore,
      transferQueue: QUEUE,
      transferSummary: { ...SUMMARY, status: 'completed', processed: 3 },
    }
    render(<Toasts />)
    expect(screen.getByText('Move completed')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Dismiss transfer panel'))
    expect(mockActions.dismissTransfer).toHaveBeenCalled()
  })

  it('shows a failed header when the confirm failed', () => {
    mockStore = {
      ...mockStore,
      transferQueue: QUEUE,
      transferSummary: { ...SUMMARY, status: 'failed' },
    }
    render(<Toasts />)
    expect(screen.getByText('Confirm failed')).toBeInTheDocument()
  })

  it('offers no dismiss while the move is still running', () => {
    mockStore = { ...mockStore, transferQueue: QUEUE, transferSummary: SUMMARY }
    render(<Toasts />)
    expect(screen.queryByLabelText('Dismiss transfer panel')).not.toBeInTheDocument()
  })
})

describe('Toasts bottom-right consolidation', () => {
  it('shows status toasts like delete confirmations in the same container', () => {
    mockStore = {
      ...mockStore,
      toasts: [
        { id: 't1', type: 'good', msg: 'Deleted: alpha.mkv' },
        { id: 't2', type: 'err', msg: 'Delete error: no such file' },
      ],
    }
    const { container } = render(<Toasts />)
    expect(container.querySelector('.transfer-toasts')).toBeTruthy()
    expect(container.querySelector('.transfer-toast.toast-good').textContent).toBe('Deleted: alpha.mkv')
    expect(container.querySelector('.transfer-toast.toast-err').textContent).toContain('Delete error: no such file')
  })

  it('offers dismiss only on error toasts, and dismisses them via the action', () => {
    mockStore = {
      ...mockStore,
      toasts: [
        { id: 't1', type: 'info', msg: 'Just info' },
        { id: 't2', type: 'err', msg: 'Move failed: disk full' },
      ],
    }
    render(<Toasts />)
    // Only the error toast gets a dismiss button (errors persist; info auto-dismisses).
    expect(screen.queryByLabelText('Dismiss error')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Dismiss error'))
    expect(mockActions.dismissToast).toHaveBeenCalledWith('t2')
  })

  it('renders nothing when there are no toasts and no activity', () => {
    const { container } = render(<Toasts />)
    expect(container.querySelector('.transfer-toasts')).toBeNull()
  })

  it('renders scan-summary toasts top-center, apart from the bottom-right container', () => {
    mockStore = {
      ...mockStore,
      toasts: [
        { id: 't1', type: 'good', msg: 'Scan complete: 2 new files found, 1 file updated', pos: 'top' },
        { id: 't2', type: 'info', msg: 'Scan started' },
      ],
    }
    const { container } = render(<Toasts />)
    const top = container.querySelector('#topCenterToasts')
    expect(top).toBeTruthy()
    expect(top.textContent).toContain('Scan complete')
    expect(top.querySelector('.transfer-toast.toast-good')).toBeTruthy()
    const bottom = container.querySelector('#transferToasts')
    expect(bottom.textContent).toContain('Scan started')
    expect(bottom.textContent).not.toContain('Scan complete')
  })
})
