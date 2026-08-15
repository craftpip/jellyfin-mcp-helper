import { describe, it, expect } from 'vitest'
import { formatBytes, formatDateTime, formatDuration, formatConfirmPhase, fileName, driveRoot, isCrossDrive, splitDrive } from './format.js'

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

describe('formatDuration', () => {
  it('formats seconds as h/m/s', () => {
    expect(formatDuration(0)).toBe('0s')
    expect(formatDuration(45)).toBe('45s')
    expect(formatDuration(90)).toBe('1m 30s')
    expect(formatDuration(3725)).toBe('1h 2m 5s')
  })

  it('handles missing/invalid input', () => {
    expect(formatDuration(null)).toBe('')
    expect(formatDuration(undefined)).toBe('')
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

describe('formatDateTime', () => {
  it('formats ISO timestamps as local YYYY-MM-DD HH:MM', () => {
    const iso = '2026-08-10T22:11:00+00:00'
    const out = formatDateTime(iso)
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    expect(new Date(out).getTime()).toBe(new Date(iso).getTime())
  })

  it('handles null and unparseable input', () => {
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime(undefined)).toBe('')
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })
})

describe('fileName', () => {
  it('returns the last path segment', () => {
    expect(fileName('/a/b/file.mkv')).toBe('file.mkv')
    expect(fileName('')).toBe('')
  })
})

describe('driveRoot', () => {
  it('extracts the first path segment as the drive root', () => {
    expect(driveRoot('/media3/torrents/Show/Ep.mkv')).toBe('/media3')
    expect(driveRoot('/mnt/disk1/series/')).toBe('/mnt')
    expect(driveRoot('')).toBe('')
  })
})

describe('isCrossDrive', () => {
  it('detects different drive roots', () => {
    expect(isCrossDrive('/media3/torrents/a.mkv', '/media2/movies/a.mkv')).toBe(true)
    expect(isCrossDrive('/media3/torrents/a.mkv', '/media3/series/a.mkv')).toBe(false)
    expect(isCrossDrive('', '/media2/x.mkv')).toBe(false)
  })
})

describe('splitDrive', () => {
  it('splits the drive root from the rest of the path', () => {
    expect(splitDrive('/media2/movies/Movie (2024)/Movie.mkv')).toEqual({
      drive: '/media2',
      rest: '/movies/Movie (2024)/Movie.mkv',
    })
    expect(splitDrive('/media3')).toEqual({ drive: '/media3', rest: '' })
    expect(splitDrive('')).toEqual({ drive: '', rest: '' })
  })
})
