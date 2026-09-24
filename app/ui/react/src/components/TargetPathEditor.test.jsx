import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TargetPathEditor from './TargetPathEditor.jsx'

const ROOTS = [
  { key: 'm2', path: '/mnt/media2t/downloads/movies', kind: 'movie', description: 'Movies' },
  { key: 's2', path: '/mnt/media2t/downloads/series', kind: 'series', description: 'Series' },
  { key: 's1', path: '/mnt/media1t/downloads/series', kind: 'series', description: 'Series' },
]

describe('TargetPathEditor', () => {
  it('splits the root into the dropdown and the remainder into the input', () => {
    render(
      <TargetPathEditor
        value="/mnt/media2t/downloads/series/Toshi Densetsu Series/Season 01/Toshi .mp4"
        roots={ROOTS}
        onChange={() => {}}
      />
    )
    expect(screen.getByLabelText('Library path').value).toBe('/mnt/media2t/downloads/series/')
    expect(screen.getByRole('textbox').value).toBe('Toshi Densetsu Series/Season 01/Toshi .mp4')
  })

  it('dropdown change swaps only the prefix', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <TargetPathEditor
        value="/mnt/media2t/downloads/series/Show/Season 01/f.mkv"
        roots={ROOTS}
        onChange={onChange}
      />
    )
    await user.selectOptions(screen.getByLabelText('Library path'), '/mnt/media1t/downloads/series/')
    expect(onChange).toHaveBeenCalledWith('/mnt/media1t/downloads/series/Show/Season 01/f.mkv')
  })

  it('remainder edit keeps the prefix', () => {
    const onChange = vi.fn()
    render(
      <TargetPathEditor value="/mnt/media2t/downloads/series/Show/Season 01/f.mkv" roots={ROOTS} onChange={onChange} />
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Show/Season 02/g.mkv' } })
    expect(onChange).toHaveBeenCalledWith('/mnt/media2t/downloads/series/Show/Season 02/g.mkv')
  })

  it('sizes the dropdown dynamically to the selected root text', () => {
    const { rerender } = render(
      <TargetPathEditor value="/mnt/media2t/downloads/series/Show/f.mkv" roots={ROOTS} onChange={() => {}} />
    )
    const select = screen.getByLabelText('Library path')
    expect(select.style.width).toBe(`calc(${('/mnt/media2t/downloads/series/').length}ch + 10px)`)
    rerender(
      <TargetPathEditor value="/mnt/media2t/downloads/movies/Movie/f.mkv" roots={ROOTS} onChange={() => {}} />
    )
    expect(screen.getByLabelText('Library path').style.width).toBe(
      `calc(${('/mnt/media2t/downloads/movies/').length}ch + 10px)`
    )
  })

  it('a pasted full path passes through so the dropdown re-splits it', () => {
    const onChange = vi.fn()
    render(
      <TargetPathEditor value="/mnt/media2t/downloads/series/Show/Season 01/f.mkv" roots={ROOTS} onChange={onChange} />
    )
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '/mnt/media1t/downloads/series/Show/Season 01/f.mkv' },
    })
    expect(onChange).toHaveBeenCalledWith('/mnt/media1t/downloads/series/Show/Season 01/f.mkv')
  })

  it('commits the full path on text-input blur', () => {
    const onCommit = vi.fn()
    render(
      <TargetPathEditor value="/mnt/media2t/downloads/series/Show/Season 01/f.mkv" roots={ROOTS} onChange={() => {}} onCommit={onCommit} />
    )
    fireEvent.blur(screen.getByRole('textbox'))
    expect(onCommit).toHaveBeenCalledWith('/mnt/media2t/downloads/series/Show/Season 01/f.mkv')
  })

  it('commits the joined path right after a dropdown change', async () => {
    const onCommit = vi.fn()
    const user = userEvent.setup()
    render(
      <TargetPathEditor
        value="/mnt/media2t/downloads/series/Show/Season 01/f.mkv"
        roots={ROOTS}
        onChange={() => {}}
        onCommit={onCommit}
      />
    )
    await user.selectOptions(screen.getByLabelText('Library path'), '/mnt/media1t/downloads/series/')
    expect(onCommit).toHaveBeenCalledWith('/mnt/media1t/downloads/series/Show/Season 01/f.mkv')
  })

  it('falls back to a full-path input with Custom… when outside all roots', () => {
    render(<TargetPathEditor value="/tmp/other/f.mkv" roots={ROOTS} onChange={() => {}} />)
    expect(screen.getByLabelText('Library path').value).toBe('__custom__')
    expect(screen.getByRole('textbox').value).toBe('/tmp/other/f.mkv')
  })

  it('renders a plain input when roots are empty', () => {
    render(<TargetPathEditor value="/a/b/f.mkv" roots={[]} onChange={() => {}} />)
    expect(screen.queryByLabelText('Library path')).toBeNull()
    expect(screen.getByRole('textbox').value).toBe('/a/b/f.mkv')
  })
})
