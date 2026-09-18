import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Toasts from './Toasts.jsx'

let mockStore

vi.mock('../store/AppStore.jsx', () => ({
  useAppStore: () => ({ state: mockStore }),
}))

const QUEUE = [
  {
    id: 'transfer-a',
    order: 0,
    sourcePath: '/media1/d/alpha.mkv',
    name: 'alpha.mkv',
    state: 'done',
    progress: null,
    doneAt: 1000,
  },
  {
    id: 'transfer-b',
    order: 1,
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
  mockStore = { toasts: [], transferQueue: [], transferSummary: null }
})

describe('Toasts transfer queue', () => {
  it('renders nothing when the queue is empty', () => {
    const { container } = render(<Toasts />)
    expect(container.querySelector('.transfer-toasts')).toBeNull()
  })

  it('collapses to the active file with live copy stats and a queue count', () => {
    mockStore = { ...mockStore, transferQueue: QUEUE, transferSummary: SUMMARY }
    const { container } = render(<Toasts />)

    expect(screen.getByText('Moving 1 of 3')).toBeInTheDocument()
    // Only the copying file is shown; done + queued rows stay hidden
    expect(screen.getByText('beta.mkv')).toBeInTheDocument()
    expect(screen.queryByText('alpha.mkv')).not.toBeInTheDocument()
    expect(screen.queryByText('gamma.mkv')).not.toBeInTheDocument()
    expect(screen.getByText('1 file in queue')).toBeInTheDocument()

    expect(screen.getByText('Moved: 1 · Replaced: 0 · Failed: 0')).toBeInTheDocument()
    expect(screen.getByText('2.3 GB / 4.1 GB')).toBeInTheDocument()
    expect(screen.getByText('21.5 MB/s')).toBeInTheDocument()
    expect(screen.getByText('ETA 1m 17s')).toBeInTheDocument()

    const copyingRow = container.querySelector('.transfer-toast.copying')
    expect(copyingRow.querySelector('.transfer-spinner')).toBeTruthy()
    expect(copyingRow.querySelector('.transfer-progress .fill.file').style.width).toBe('60%')
  })

  it('expands to the full list and collapses again', () => {
    mockStore = { ...mockStore, transferQueue: QUEUE, transferSummary: SUMMARY }
    const { container } = render(<Toasts />)

    fireEvent.click(screen.getByText('Show all 3'))
    expect(screen.getByText('alpha.mkv')).toBeInTheDocument()
    expect(screen.getByText('beta.mkv')).toBeInTheDocument()
    expect(screen.getByText('gamma.mkv')).toBeInTheDocument()
    expect(container.querySelector('.transfer-queue.expanded')).toBeTruthy()
    const doneRow = container.querySelector('.transfer-toast.done')
    expect(doneRow.querySelector('.transfer-tick')).toBeTruthy()

    fireEvent.click(screen.getByText('Show less'))
    expect(screen.queryByText('alpha.mkv')).not.toBeInTheDocument()
    expect(screen.getByText('beta.mkv')).toBeInTheDocument()
  })

  it('shows the next queued file before the copy starts', () => {
    const queuedOnly = QUEUE.map((t) => ({ ...t, state: 'queued', progress: null }))
    mockStore = {
      ...mockStore,
      transferQueue: queuedOnly,
      transferSummary: { ...SUMMARY, processed: 0 },
    }
    render(<Toasts />)
    expect(screen.getByText('Up next')).toBeInTheDocument()
    expect(screen.getByText('alpha.mkv')).toBeInTheDocument()
    expect(screen.queryByText('beta.mkv')).not.toBeInTheDocument()
    expect(screen.getByText('2 files in queue')).toBeInTheDocument()
  })

  it('hides the queue count when nothing is waiting', () => {
    const solo = [QUEUE[1]]
    mockStore = {
      ...mockStore,
      transferQueue: solo,
      transferSummary: { processed: 0, total: 1, status: 'running', counts: {} },
    }
    render(<Toasts />)
    expect(screen.getByText('beta.mkv')).toBeInTheDocument()
    expect(screen.queryByText(/in queue/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Show all/)).not.toBeInTheDocument()
  })

  it('shows a completed header when the move is done', () => {
    mockStore = {
      ...mockStore,
      transferQueue: QUEUE,
      transferSummary: { ...SUMMARY, status: 'completed', processed: 3 },
    }
    const { container } = render(<Toasts />)
    expect(screen.getByText('Move completed')).toBeInTheDocument()
    // No live row in terminal states — details stay behind the expander
    expect(container.querySelector('.transfer-queue .transfer-toast')).toBeNull()
    fireEvent.click(screen.getByText('Show all 3'))
    expect(screen.getByText('alpha.mkv')).toBeInTheDocument()
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
    expect(container.querySelector('.transfer-toast.toast-err').textContent).toBe('Delete error: no such file')
  })

  it('renders nothing when there are no toasts and no activity', () => {
    const { container } = render(<Toasts />)
    expect(container.querySelector('.transfer-toasts')).toBeNull()
  })
})
