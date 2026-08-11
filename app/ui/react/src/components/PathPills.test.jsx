import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PathPills from './PathPills.jsx'

describe('PathPills', () => {
  it('renders series Show/Season/File pills with correct states', () => {
    render(<PathPills item={{ itemType: 'series', pathExists: 'Show ✓, Season ✗, File ✓' }} />)
    expect(screen.getByLabelText(/^Show:/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^Show:/)).toHaveClass('exists')
    expect(screen.getByLabelText(/^Season:/)).toHaveClass('missing')
    expect(screen.getByLabelText(/^File:/)).toHaveClass('exists')
  })

  it('renders movie Folder/File pills', () => {
    render(<PathPills item={{ itemType: 'movie', pathExists: 'Folder ✗, File ✗' }} />)
    expect(screen.getByLabelText(/^Folder:/)).toHaveClass('missing')
    expect(screen.getByLabelText(/^File:/)).toHaveClass('missing')
  })
})
