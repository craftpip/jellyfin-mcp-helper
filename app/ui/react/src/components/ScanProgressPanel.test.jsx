import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ScanProgressPanel from './ScanProgressPanel.jsx'

describe('ScanProgressPanel', () => {
  it('shows a loading state with no zeros while the scan is starting', () => {
    render(<ScanProgressPanel progress={{ status: 'running', processed: 0, total: 0, percent: 0 }} />)

    expect(screen.getByText('Starting scan...')).toBeInTheDocument()
    expect(screen.getByText('Preparing the scan plan...')).toBeInTheDocument()
    expect(screen.getByText('Starting scan...').closest('.progress-center').querySelector('.spinner')).toBeTruthy()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
    expect(screen.queryByText(/0\/0/)).not.toBeInTheDocument()
    expect(screen.queryByText(/0s/)).not.toBeInTheDocument()
  })

  it('shows the running layout with real numbers once the plan has a total', () => {
    render(<ScanProgressPanel progress={{ status: 'running', processed: 5, total: 1700, percent: 0.3, elapsed: '2s' }} />)

    expect(screen.getByText('Scanning...')).toBeInTheDocument()
    expect(screen.getByText('0%')).toBeInTheDocument()
    expect(screen.getByText('5/1700 · 2s')).toBeInTheDocument()
    expect(screen.queryByText('Starting scan...')).not.toBeInTheDocument()
  })
})
