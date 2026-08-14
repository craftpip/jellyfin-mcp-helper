import { describe, it, expect } from 'vitest'
import { buildTransferQueue, deriveTransferQueue } from './transfer.js'

const ITEMS = [
  { confirmId: 'a', sourceName: 'alpha.mkv', sourcePath: '/media1/d/alpha.mkv', targetPath: '/media2/s/Alpha/Alpha.mkv' },
  { confirmId: 'b', sourceName: 'beta.mkv', sourcePath: '/media1/d/beta.mkv', targetPath: '/media2/s/Beta/Beta.mkv' },
  { confirmId: 'c', sourceName: 'gamma.mkv', sourcePath: '/media1/d/gamma.mkv', targetPath: '/media2/s/Gamma/Gamma.mkv' },
]

describe('buildTransferQueue', () => {
  it('creates queued items in itemIds order, skipping unknown ids', () => {
    const queue = buildTransferQueue(['b', 'zzz', 'c'], ITEMS)
    expect(queue.map((t) => t.name)).toEqual(['beta.mkv', 'gamma.mkv'])
    expect(queue.map((t) => t.order)).toEqual([0, 1])
    expect(queue.every((t) => t.state === 'queued')).toBe(true)
    expect(queue.every((t) => t.doneAt === null && t.progress === null)).toBe(true)
  })
})

describe('deriveTransferQueue', () => {
  it('marks finished items done and the current file copying with live progress', () => {
    const queue = buildTransferQueue(['a', 'b', 'c'], ITEMS)
    const result = {
      status: 'running',
      processed: 1,
      total: 3,
      current_file: '/media1/d/beta.mkv',
      current_percent: 45.5,
      current_speed: '21.5 MB/s',
      current_speed_bytes: 21500000,
      current_eta: '1m 17s',
      current_size_bytes: 4402341478,
      current_copied_bytes: 2000000000,
      counts: { moved: 1, replaced: 0, failed: 0 },
    }
    const { queue: next, state } = deriveTransferQueue(queue, result, { completed: 0, failed: 0 }, 1000000)

    expect(state).toEqual({ completed: 1, failed: 0 })
    expect(next[0].state).toBe('done')
    expect(next[0].doneAt).toBe(1000000)
    expect(next[1].state).toBe('copying')
    expect(next[1].progress.percent).toBe(45.5)
    expect(next[1].progress.speed).toBe('21.5 MB/s')
    expect(next[1].progress.eta).toBe('1m 17s')
    expect(next[2].state).toBe('queued')
    expect(next[2].doneAt).toBeNull()
  })

  it('keeps doneAt stable across polls and does not regress completed', () => {
    const queue = buildTransferQueue(['a', 'b', 'c'], ITEMS)
    const first = deriveTransferQueue(queue, {
      status: 'running', processed: 1, current_file: '/media1/d/beta.mkv', counts: { moved: 1, failed: 0 },
    }, { completed: 0, failed: 0 }, 1000)

    const second = deriveTransferQueue(first.queue, {
      status: 'running', processed: 1, current_file: '/media1/d/beta.mkv',
      current_percent: 60, current_speed: '20 MB/s', current_eta: '40s',
      current_size_bytes: 10, current_copied_bytes: 6,
      counts: { moved: 1, failed: 0 },
    }, first.state, 3000)

    expect(second.queue[0].state).toBe('done')
    expect(second.queue[0].doneAt).toBe(1000)
    expect(second.queue[1].state).toBe('copying')
    expect(second.queue[1].progress.percent).toBe(60)
    expect(second.queue[2].state).toBe('queued')
  })

  it('marks the failing items when counts.failed increases across a poll', () => {
    const queue = buildTransferQueue(['a', 'b', 'c'], ITEMS)
    const { queue: q2 } = deriveTransferQueue(queue, {
      status: 'running', processed: 2, current_file: '/media1/d/gamma.mkv', counts: { moved: 1, failed: 1 },
    }, { completed: 0, failed: 0 }, 5000)

    expect(q2[0].state).toBe('done')
    expect(q2[1].state).toBe('failed')
    expect(q2[2].state).toBe('copying')
  })

  it('marks every unfinished item failed when the whole confirm fails', () => {
    const queue = buildTransferQueue(['a', 'b', 'c'], ITEMS)
    const { queue: q2 } = deriveTransferQueue(queue, {
      status: 'failed', processed: 1, counts: { moved: 1, failed: 0 },
    }, { completed: 0, failed: 0 }, 6000)

    expect(q2[0].state).toBe('done')
    expect(q2[1].state).toBe('failed')
    expect(q2[2].state).toBe('failed')
    expect(q2[1].doneAt).toBe(6000)
  })

  it('stays queued when idle (no confirm started) and a stale poll arrives', () => {
    const queue = buildTransferQueue(['a', 'b', 'c'], ITEMS)
    const { queue: q2 } = deriveTransferQueue(queue, {
      status: 'idle', processed: 0, counts: {},
    }, { completed: 0, failed: 0 }, 7000)

    expect(q2.map((t) => t.state)).toEqual(['queued', 'queued', 'queued'])
  })
})
