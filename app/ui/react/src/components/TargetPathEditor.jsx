import { joinTarget, splitTarget } from '../utils/report.js'

// Shared by ReportPanel and HistoryPage (row chrome must stay in sync).
// One joined group: [library-root dropdown][remainder text input].
// The dropdown holds the slash-terminated root prefix; the input holds
// everything after it. Callers always get/set the full target path.
// onCommit(fullPath) fires on text-input blur and right after a dropdown
// change so callers can refresh live affordances (path-status pills).
export default function TargetPathEditor({ value, roots, onChange, onCommit, onKeyDown, placeholder, ariaLabel }) {
  const list = Array.isArray(roots) ? roots : []
  if (!list.length) {
    return (
      <input
        type="text"
        className="target-input"
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        onBlur={(e) => { if (onCommit) onCommit(e.target.value) }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label={ariaLabel}
        style={{ flex: 1, minWidth: 0 }}
      />
    )
  }
  const full = value || ''
  const { root, remainder } = splitTarget(full, list)
  const custom = !root
  const selectValue = custom ? '__custom__' : root
  // Dynamic width: the type is monospace, so 1ch == 1 char — size the
  // select to the visible root text (+ horizontal padding) so it grows and
  // shrinks with the selection instead of using a fixed width.
  const visibleRoot = custom ? 'Custom…' : root
  const selectWidth = `calc(${visibleRoot.length}ch + 10px)`
  const movies = list.filter((r) => (r.kind || '') === 'movie')
  const series = list.filter((r) => (r.kind || '') === 'series')
  const others = list.filter((r) => (r.kind || '') !== 'movie' && (r.kind || '') !== 'series')

  function startsWithKnownRoot(raw) {
    return list.some((r) => {
      const p = (r.path || r || '').replace(/\/+$/, '')
      return p && (raw === p || raw === p + '/' || raw.startsWith(p + '/'))
    })
  }

  function optionLabel(r) {
    const path = r.path || r
    const desc = r.description || ''
    return desc && desc !== path ? `${path} (${desc})` : path
  }

  function renderOptions(items) {
    return items.map((r) => {
      const path = r.path || r
      const key = r.key || path
      const slashPath = path.endsWith('/') ? path : path + '/'
      const desc = r.description || ''
      return (
        <option key={key} value={slashPath} title={desc ? `${desc} — ${slashPath}` : slashPath}>
          {optionLabel(r)}
        </option>
      )
    })
  }

  return (
    <div className="target-path-group">
      <span className="target-root-wrap">
        <select
          className="target-root-select"
          value={selectValue}
          style={{ width: selectWidth }}
          onChange={(e) => {
            if (e.target.value === '__custom__') return
            const full = joinTarget(e.target.value, remainder)
            onChange(full)
            if (onCommit) onCommit(full)
          }}
          title={custom ? 'Current path is outside known libraries — pick a library to move it under one' : 'Library path — click to switch libraries'}
          aria-label="Library path"
        >
          {custom && (
            <option value="__custom__" disabled>
              Custom…
            </option>
          )}
          {movies.length > 0 && <optgroup label="Movies">{renderOptions(movies)}</optgroup>}
          {series.length > 0 && <optgroup label="Series">{renderOptions(series)}</optgroup>}
          {others.length > 0 && <optgroup label="Other">{renderOptions(others)}</optgroup>}
          {movies.length === 0 && series.length === 0 && renderOptions(list)}
        </select>
      </span>
      <input
        type="text"
        className="target-input"
        value={custom ? full : remainder}
        onChange={(e) => {
          if (custom) onChange(e.target.value)
          // A pasted full path (starting with a known root) passes through
          // untouched so the dropdown re-splits it on the next render.
          else if (startsWithKnownRoot(e.target.value)) onChange(e.target.value)
          else onChange(joinTarget(root, e.target.value))
        }}
        onBlur={() => { if (onCommit) onCommit(full) }}
        onKeyDown={onKeyDown}
        placeholder={placeholder || 'relative/path…'}
        aria-label={ariaLabel}
        style={{ flex: 1, minWidth: 0 }}
      />
    </div>
  )
}
