import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
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

  it('shows the queue with done tick, live copy stats, and queued waiters', () => {
    mockStore = { ...mockStore, transferQueue: QUEUE, transferSummary: SUMMARY }
    const { container } = render(<Toasts />)

    expect(screen.getByText('Moving 1 of 3')).toBeInTheDocument()
    expect(screen.getByText('alpha.mkv')).toBeInTheDocument()
    expect(screen.getByText('beta.mkv')).toBeInTheDocument()
    expect(screen.getByText('gamma.mkv')).toBeInTheDocument()

    expect(screen.getByText('Moved: 1 · Replaced: 0 · Failed: 0')).toBeInTheDocument()
    expect(screen.getByText('2.3 GB / 4.1 GB')).toBeInTheDocument()
    expect(screen.getByText('21.5 MB/s')).toBeInTheDocument()
    expect(screen.getByText('ETA 1m 17s')).toBeInTheDocument()

    const doneRow = container.querySelector('.transfer-toast.done')
    expect(doneRow.querySelector('.transfer-tick')).toBeTruthy()
    const copyingRow = container.querySelector('.transfer-toast.copying')
    expect(copyingRow.querySelector('.transfer-spinner')).toBeTruthy()
    expect(copyingRow.querySelector('.transfer-progress .fill.file').style.width).toBe('60%')
  })

  it('shows a completed header when the move is done', () => {
    mockStore = {
      ...mockStore,
      transferQueue: QUEUE,
      transferSummary: { ...SUMMARY, status: 'completed', processed: 3 },
    }
    render(<Toasts />)
    expect(screen.getByText('Move completed')).toBeInTheDocument()
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
