import { useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { formatBytes } from '../utils/format.js'
import { matchesFilter } from '../utils/report.js'
import PathPills from './PathPills.jsx'

const FILTER_DEFS = [
  ['all', 'All'],
  ['move', 'New'],
  ['replace', 'Replace'],
  ['existing', 'Existing path'],
  ['new', 'New path'],
]

export default function ReportPanel() {
  const { state, actions } = useAppStore()
  const [query, setQuery] = useState('')
  const {
    reportVisible,
    reportAll,
    reportSummary,
    currentItems,
    reportGroups,
    currentFilter,
    rowLimit,
    selectedIds,
    expandedGroups,
  } = state

  if (!reportVisible) return null

  const actionable = reportAll.filter((i) => i.action !== 'skip')
  const counts = {
    all: actionable.length,
    move: actionable.filter((i) => i.action === 'move').length,
    replace: actionable.filter((i) => i.action === 'replace').length,
    existing: actionable.filter((i) => i.fileExists).length,
    new: actionable.filter((i) => !i.fileExists).length,
  }
  const hasItems = actionable.length > 0

  // Mirror the legacy updateSelectionSummary: "visible" = actionable rows in
  // expanded groups (filter-independent), selected among them.
  let visibleActionable = 0
  let selectedVisible = 0
  reportGroups.forEach((group, gi) => {
    if (!expandedGroups.includes('group-' + gi)) return
    group.items.forEach((item) => {
      if (item.action === 'skip') return
      visibleActionable += 1
      if (selectedIds.includes(item.confirmId)) selectedVisible += 1
    })
  })

  let selectionSummary
  if (visibleActionable > 0) {
    selectionSummary = selectedVisible + ' of ' + visibleActionable + ' item(s) selected'
  } else if (hasItems) {
    selectionSummary =
      '0 of 0 visible (of ' + actionable.length + ' total, try adjusting filters)'
  } else {
    selectionSummary = 'No report items loaded yet.'
  }

  const summary = reportSummary || {}
  const hiddenCount = Math.max(0, reportAll.length - currentItems.length)

  return (
    <div className="panel" id="reportPanel">
      <h2>Scan Report</h2>
      <div className="summary-strip">
        {[
          ['Movies', summary.movies ?? 0, ''],
          ['Series', summary.series ?? 0, ''],
          ['Skipped', summary.skipped ?? 0, '#8b949e'],
          ['Actions Needed', summary.action_required ?? 0, '#d29922'],
        ].map(([label, value, color]) => (
          <div className="summary-pill" key={label} style={color ? { color } : undefined}>
            <strong>{value}</strong> {label}
          </div>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '4px', alignItems: 'center' }}>
          {summary.scan_id && (
            <span
              onClick={() => actions.copyText(summary.scan_id)}
              style={{
                cursor: 'pointer',
                borderBottom: '1px dashed #8b949e',
                color: '#8b949e',
                fontSize: '0.8rem',
              }}
              title="Click to copy"
            >
              scan_id: {summary.scan_id}
            </span>
          )}
          <button className="small" onClick={() => actions.toggleAllGroups(false)}>
            Collapse all
          </button>
          <button className="small" onClick={() => actions.toggleAllGroups(true)}>
            Expand all
          </button>
        </div>
      </div>

      <div className="search-bar">
        <input
          type="text"
          id="filterInput"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title, path..."
        />
        <select
          id="rowLimit"
          value={rowLimit}
          onChange={(e) => actions.setRowLimit(parseInt(e.target.value, 10) || 0)}
          title="Maximum rows rendered at once"
        >
          <option value="50">Show 50</option>
          <option value="100">Show 100</option>
          <option value="500">Show 500</option>
          <option value="0">Show all</option>
        </select>
      </div>

      <div className="filter-chips" id="filterChips">
        {FILTER_DEFS.map(([k, label]) => (
          <button
            key={k}
            className={'filter-chip' + (currentFilter === k ? ' active' : '')}
            onClick={() => actions.setFilter(k)}
          >
            {label} <span className="chip-count">{counts[k]}</span>
          </button>
        ))}
      </div>

      <div className="report-toolbar">
        <div className="hint" id="selectionSummary">
          {selectionSummary}
        </div>
        <div className="report-actions">
          <button className="small" id="btnSelectAll" disabled={!hasItems} onClick={() => actions.setCheckedItems('all')}>
            Select All
          </button>
          <button className="small" id="btnSelectNone" disabled={!hasItems} onClick={() => actions.setCheckedItems('none')}>
            Select None
          </button>
          <button className="small" id="btnSelectExisting" disabled={!hasItems} onClick={() => actions.setCheckedItems('existing')}>
            Select existing paths
          </button>
          <button className="small" id="btnSelectMove" disabled={!hasItems} onClick={() => actions.setCheckedItems('move')}>
            Select all new
          </button>
          <button className="small" id="btnSelectReplace" disabled={!hasItems} onClick={() => actions.setCheckedItems('replace')}>
            Select all existing
          </button>
        </div>
      </div>

      <div id="reportItems">
        {reportGroups.length === 0 && (
          <div style={{ color: '#8b949e' }}>No items to review.</div>
        )}
        {reportGroups.map((group, gi) => {
          const gid = 'group-' + gi
          const expanded = expandedGroups.includes(gid)
          const visibleItems = group.items.filter((item) => matchesFilter(item, query, currentFilter))
          if (visibleItems.length === 0) return null
          return (
            <ReportGroup
              key={gid}
              gid={gid}
              gi={gi}
              group={group}
              expanded={expanded}
              visibleItems={visibleItems}
              query={query}
              filter={currentFilter}
            />
          )
        })}
      </div>

      {hiddenCount > 0 && (
        <div className="hint mt-8" id="reportLimitHint">
          Showing {currentItems.length} of {reportAll.length} items — raise the "Show" limit above to render
          more, or filter with the chips.
        </div>
      )}
    </div>
  )
}

function ReportGroup({ gid, gi, group, expanded, visibleItems }) {
  const { state, actions } = useAppStore()
  const isSeries = group.items[0].itemType === 'series'
  const skipOnly = group.items.every((i) => i.action === 'skip')
  const allChecked =
    group.items.length > 0 &&
    group.items.every((i) => state.selectedIds.includes(i.confirmId))

  return (
    <>
      <div className="group-header" onClick={() => actions.toggleGroup(gid)}>
        <span className={'arrow' + (expanded ? '' : ' collapsed')}>▾</span>
        <span className="g-title">{group.title}</span>
        <span className="g-count">{group.items.length} item(s)</span>
        {group.totalSize > 0 && <span className="g-size">{formatBytes(group.totalSize)}</span>}
      </div>
      <div className={'group-body' + (expanded ? '' : ' collapsed')}>
        <div className="group-toolbar">
          <label className="chk-label" onClick={(e) => e.stopPropagation()}>
            <input
              type="checkbox"
              className="group-select-all"
              checked={allChecked}
              onChange={(e) => actions.toggleGroupSelect(gi, e.target.checked)}
            />
            <span className="chk-text">{group.title}</span>
          </label>
          {!skipOnly && (
            <a
              className="search-btn"
              href={'https://duckduckgo.com/?q=' + encodeURIComponent(group.title)}
              target="_blank"
              rel="noreferrer"
              title="Search DuckDuckGo for this show"
            >
              Search
            </a>
          )}
          <button className="small" onClick={() => actions.toggleGroupSelect(gi, true)}>
            All
          </button>
          <button className="small" onClick={() => actions.toggleGroupSelect(gi, false)}>
            None
          </button>
          {skipOnly ? (
            <button className="danger small" style={{ marginLeft: '8px' }} onClick={() => actions.deleteSelectedSkipped(gi)}>
              Delete Selected
            </button>
          ) : (
            <>
              <button className="primary small" style={{ marginLeft: '8px' }} onClick={() => actions.applyGroupTargetEdits(gi)}>
                Update Paths
              </button>
              <button className="warn small" onClick={() => actions.confirmGroup(gi)}>
                Confirm
              </button>
            </>
          )}
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ width: '40px' }} />
              <th style={{ width: '150px' }}>Action</th>
              {isSeries && <th style={{ width: '90px' }}>Episode</th>}
              <th colSpan={2}>Source → Target Path</th>
              <th style={{ width: '90px' }}>Size</th>
              <th style={{ width: '110px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visibleItems.map((item) => (
              <ReportRow key={item.confirmId} item={item} isSeries={isSeries} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function ReportRow({ item, isSeries }) {
  const { state, actions } = useAppStore()
  const selected = state.selectedIds.includes(item.confirmId)
  const liveTarget = item._liveTarget || item.targetPath

  if (item.action === 'skip') {
    return (
      <tr className="row-skipped">
        <td>
          <input
            type="checkbox"
            className="item-check skip-check"
            checked={selected}
            onChange={(e) => actions.selectItem(item.confirmId, e.target.checked)}
          />
        </td>
        <td>
          <div className="action-cell">
            <span className="badge action-skip">Skipped</span>
          </div>
        </td>
        {isSeries && <td />}
        <td colSpan={2}>
          <div className="path-cell">
            <div className="source-name" title={item.sourcePath || item.sourceName || ''}>
              {item.sourcePath || item.sourceName || ''}
            </div>
            <span className="skip-reason">{item.reason || ''}</span>
          </div>
        </td>
        <td style={{ whiteSpace: 'nowrap', color: '#8b949e', fontSize: '0.8rem' }}>
          {item.fileSize ? formatBytes(item.fileSize) : ''}
        </td>
        <td style={{ textAlign: 'right' }}>
          <button
            className="danger small"
            onClick={() => actions.deleteSourceItem(item._idx)}
            title="Delete the source download file"
          >
            Delete
          </button>
        </td>
      </tr>
    )
  }

  const actionLabel = item.action === 'replace' ? 'Existing' : 'New'
  return (
    <tr data-title={item.title.toLowerCase()} data-action={item.action} data-fileexists={item.fileExists ? 'true' : 'false'}>
      <td>
        <input
          type="checkbox"
          className="item-check"
          checked={selected}
          onChange={(e) => actions.selectItem(item.confirmId, e.target.checked)}
        />
      </td>
      <td>
        <div className="action-cell">
          <span className={'badge action-' + item.action}>{actionLabel}</span>
          {item.crossDrive && (
            <span className="crossdrive-badge" title="This item moves between different drives — the copy+delete takes longer">
              Cross-drive
            </span>
          )}
          <span className="path-status">
            <PathPills item={item} />
          </span>
        </div>
      </td>
      {isSeries && <td>{item.episode || ''}</td>}
      <td colSpan={2}>
        <div className="path-cell">
          <div className="source-name" title={item.sourcePath || item.sourceName || ''}>
            {item.sourcePath || item.sourceName || ''}
          </div>
          <input
            type="text"
            className="target-input"
            value={liveTarget}
            onChange={(e) =>
              actions.onTargetInputChange(item._idx, e.target.value, e.nativeEvent.inputType === 'insertFromPaste')
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.currentTarget.closest('.group-body')?.querySelector('.primary.small')?.focus()
              }
            }}
          />
        </div>
      </td>
      <td style={{ whiteSpace: 'nowrap', color: '#8b949e', fontSize: '0.8rem' }}>
        {item.fileSize ? formatBytes(item.fileSize) : ''}
      </td>
      <td style={{ textAlign: 'right' }}>
        <button
          className="danger small"
          onClick={() => actions.deleteSourceItem(item._idx)}
          title="Delete the source download file (not the target)"
        >
          Delete
        </button>
      </td>
    </tr>
  )
}
