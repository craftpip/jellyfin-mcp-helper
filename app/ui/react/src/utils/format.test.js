import { describe, it, expect } from 'vitest'
import { formatBytes, formatConfirmPhase, fileName } from './format.js'

describe('formatBytes', () => {
  it('formats bytes with units', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1073741824)).toBe('1.0 GB')
    expect(formatBytes(536870912)).toBe('512.0 MB')
  })

  it('handles undefined/null', () => {
    expect(formatBytes(undefined)).toBe('')
    expect(formatBytes(null)).toBe('')
  })
})

describe('formatConfirmPhase', () => {
  it('maps known phases and falls back to Running', () => {
    expect(formatConfirmPhase('preparing')).toBe('Preparing')
    expect(formatConfirmPhase('moving')).toBe('Copying or moving')
    expect(formatConfirmPhase('deleting_source')).toBe('Removing source')
    expect(formatConfirmPhase('completed')).toBe('Completed')
    expect(formatConfirmPhase('mystery')).toBe('Running')
  })
})

describe('fileName', () => {
  it('returns the last path segment', () => {
    expect(fileName('/a/b/file.mkv')).toBe('file.mkv')
    expect(fileName('')).toBe('')
  })
})
