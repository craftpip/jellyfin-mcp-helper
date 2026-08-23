import { useAppStore } from '../store/AppStore.jsx'
import { formatBytes } from '../utils/format.js'
import { matchesFilter, isCrossDriveItem } from '../utils/report.js'
import PathPills from './PathPills.jsx'

function highlight(text, query) {
  if (!query || !text) return text
  const q = query.trim()
  if (!q) return text
  const lower = text.toLowerCase()
  const idx = lower.indexOf(q.toLowerCase())
  if (idx === -1) return text
  const before = text.slice(0, idx)
  const match = text.slice(idx, idx + q.length)
  const after = text.slice(idx + q.length)
  return (
    <>
      {before}
      <mark style={{ background: 'rgba(0,164,220,0.25)', color: 'inherit', padding: '0 1px', borderRadius: '2px' }}>{match}</mark>
      {after}
    </>
  )
}

const FILTER_DEFS = [
  ['all', 'All'],
  ['move', 'New'],
  ['replace', 'Replace'],
  ['extra', 'Extras'],
  ['existing', 'Existing path'],
  ['new', 'New path'],
]

export default function ReportPanel() {
  const { state, actions } = useAppStore()
  const query = state.searchQuery || ''
  const {
    reportVisible,
    reportAll,
    reportSummary,
    reportGroups,
    currentFilter,
    selectedIds,
    expandedGroups,
  } = state

  if (!reportVisible) return null

  const actionable = reportAll.filter((i) => i.action !== 'skip')
  const skipped = reportAll.filter((i) => i.action === 'skip')
  const counts = {
    all: actionable.length,
    move: actionable.filter((i) => i.action === 'move').length,
    replace: actionable.filter((i) => i.action === 'replace').length,
    extra: actionable.filter((i) => i.itemType === 'extra').length,
    existing: actionable.filter((i) => i.fileExists).length,
    new: actionable.filter((i) => !i.fileExists).length,
  }
  const hasItems = actionable.length > 0
  const hasSkippedOnly = !hasItems && skipped.length > 0
  const skippedSize = skipped.reduce((s, i) => s + (Number(i.fileSize) || 0), 0)

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
  } else if (hasSkippedOnly) {
    selectionSummary = skipped.length + ' skipped — nothing to move right now'
  } else {
    selectionSummary = 'No report items loaded yet.'
  }

  const summary = reportSummary || {}

  return (
    <div className="panel" id="reportPanel">
      <h2>Scan Report</h2>
      <div className="summary-strip">
        {[
          ['Movies', summary.movies ?? 0, ''],
          ['Series', summary.series ?? 0, ''],
          ['Skipped', summary.skipped ?? 0, '#9aa4ab'],
          ['Actions Needed', summary.action_required ?? 0, '#e8b34b'],
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
                borderBottom: '1px dashed #9aa4ab',
                color: '#9aa4ab',
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

      {state.reportServiceErrors && Object.keys(state.reportServiceErrors).length > 0 && (() => {
        const keys = Object.keys(state.reportServiceErrors)
        const onlyQbit = keys.length === 1 && keys[0] === 'qBittorrent'
        return (
          <div className="warn-box" style={{ marginTop: '12px' }}>
            {onlyQbit ? (
              <><strong>qBittorrent check skipped</strong> — could not reach download client (in-progress check disabled).</>
            ) : (
              <><strong>Some paths could not be scanned</strong> — check skipped items below.</>
            )}
            {Object.entries(state.reportServiceErrors).map(([k, v]) => (
              <div key={k} style={{ marginTop: '6px', fontSize: '0.82rem', wordBreak: 'break-word' }}>
                <strong>{k}:</strong> {typeof v === 'string' ? v.slice(0, 300) : JSON.stringify(v).slice(0, 300)}
              </div>
            ))}
            {onlyQbit && (
              <div style={{ marginTop: '6px', fontSize: '0.78rem', color: 'var(--jf-text-muted)' }}>
                Tip: set <code>ENABLE_DOWNLOAD_CLIENT_CHECK=false</code> in .env if you don&apos;t use qBittorrent, or check <code>QBT_MCP_URL</code> is reachable.
              </div>
            )}
          </div>
        )
      })()}

      {!hasItems && (
        <div className={'empty-celebration' + (hasSkippedOnly ? ' has-skipped' : '')}>
          {hasSkippedOnly ? (
            <>
              <div className="empty-icon">✓</div>
              <div>
                <strong>All caught up</strong> — nothing to move. {skipped.length} file(s) skipped {skippedSize ? '(' + formatBytes(skippedSize) + ')' : ''}{skipped.every((i) => (i.reason || '').toLowerCase().includes('in-progress')) ? ' — in-progress downloads will appear after they finish' : ''}.
              </div>
            </>
          ) : (
            <>
              <div className="empty-icon">○</div>
              <div>No items to review. Run a scan to see what can be organized.</div>
            </>
          )}
        </div>
      )}

      <div className="search-bar">
        <input
          type="text"
          id="filterInput"
          value={query}
          onChange={(e) => actions.setSearchQuery(e.target.value)}
          placeholder="Search by title, path..."
        />
        {query && (
          <button className="small" onClick={() => actions.setSearchQuery('')} title="Clear search">
            Clear
          </button>
        )}
      </div>

      {hasItems && (
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
      )}

      <div className="report-toolbar">
        <div className="hint" id="selectionSummary">
          {selectionSummary}
        </div>
        {hasItems && (
          <div className="report-actions">
            <button className="small" id="btnSelectAll" onClick={() => actions.setCheckedItems('all')}>
              Select All
            </button>
            <button className="small" id="btnSelectNone" onClick={() => actions.setCheckedItems('none')}>
              Select None
            </button>
            <button className="small" id="btnSelectExisting" onClick={() => actions.setCheckedItems('existing')}>
              Select existing paths
            </button>
            <button className="small" id="btnSelectMove" onClick={() => actions.setCheckedItems('move')}>
              Select all new
            </button>
            <button className="small" id="btnSelectReplace" onClick={() => actions.setCheckedItems('replace')}>
              Select all existing
            </button>
          </div>
        )}
      </div>

      <div id="reportItems">
        {reportGroups.length === 0 && (
          <div style={{ color: '#9aa4ab' }}>No items to review.</div>
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
    </div>
  )
}

function ReportGroup({ gid, gi, group, expanded, visibleItems, query }) {
  const { state, actions } = useAppStore()
  const isSeries = group.items[0].itemType === 'series'
  const skipOnly = group.items.every((i) => i.action === 'skip')
  const hasPathEdits = group.items.some(
    (i) => ((i._liveTarget || i.targetPath) || '').trim() !== ((i.originalTarget || i.targetPath) || '').trim()
  )
  const allChecked =
    group.items.length > 0 &&
    group.items.every((i) => state.selectedIds.includes(i.confirmId))

  return (
    <>
      <div className={'group-header' + (expanded ? ' expanded' : ' collapsed')} onClick={() => actions.toggleGroup(gid)}>
        <span className={'arrow' + (expanded ? '' : ' collapsed')}>▾</span>
        <span className="g-title">{highlight(group.title, query)}</span>
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
              title={'Search for "' + group.title + '" on DuckDuckGo (opens in a new tab)'}
            >
              Search
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
                <path d="M7 17L17 7" />
                <path d="M8 7h9v9" />
              </svg>
            </a>
          )}
          {skipOnly ? (
            <button className="danger small" style={{ marginLeft: '8px' }} onClick={() => actions.deleteSelectedSkipped(gi)}>
              Delete Selected
            </button>
          ) : hasPathEdits ? (
            <button className="primary small" style={{ marginLeft: '8px' }} onClick={() => actions.applyGroupTargetEdits(gi)}>
              Update Paths
            </button>
          ) : (
            <button className="warn small" onClick={() => actions.confirmGroup(gi)}>
              Confirm
            </button>
          )}
        </div>
        <table>
          <thead>
            <tr>
              <th style={{ width: '40px' }} />
              <th style={{ width: '150px' }}>Action</th>
              {isSeries && <th style={{ width: '90px' }}>Episode</th>}
              <th colSpan={2}>Source → Target Path</th>
              <th style={{ width: '90px', textAlign: 'right' }}>Size</th>
              <th style={{ width: '70px', textAlign: 'right' }}></th>
            </tr>
          </thead>
          <tbody>
            {visibleItems.map((item) => (
              <ReportRow key={item.confirmId} item={item} isSeries={isSeries} query={query} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function ReportRow({ item, isSeries, query }) {
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
              {highlight(item.sourcePath || item.sourceName || '', query)}
            </div>
            <span className="skip-reason">{highlight(item.reason || '', query)}</span>
          </div>
        </td>
        <td style={{ whiteSpace: 'nowrap', textAlign: 'right', color: '#9aa4ab', fontSize: '0.8rem' }}>
          {item.fileSize ? formatBytes(item.fileSize) : ''}
        </td>
        <td style={{ textAlign: 'right' }}>
          <button
            className="danger small"
            onClick={() => actions.deleteSourceItem(item._idx)}
            title="Delete the source file"
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
          {isCrossDriveItem(item) && (
            <span className="crossdrive-badge" title="Moved between hard drives — will take some time">
              Cross-drive
            </span>
          )}
          {item.suspect && (
            <span className="suspect-badge" title={item.correctionNote || 'Suspect classification — double-check the target'}>
              Suspect
            </span>
          )}
          {item.corrected && (
            <span className="corrected-badge" title={item.correctionNote || 'Reclassified after review'}>
              Corrected
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
            {highlight(item.sourcePath || item.sourceName || '', query)}
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
          <div className="target-tools">
            <button className="small browse-btn" onClick={() => actions.openBrowse(item.confirmId)}>
              Browse…
            </button>
          </div>
        </div>
      </td>
      <td style={{ whiteSpace: 'nowrap', textAlign: 'right', color: '#9aa4ab', fontSize: '0.8rem' }}>
        {item.fileSize ? formatBytes(item.fileSize) : ''}
      </td>
      <td style={{ textAlign: 'right' }}>
        <button
          className="danger small"
          onClick={() => actions.deleteSourceItem(item._idx)}
          title="Delete the source file (not the target)"
        >
          Delete
        </button>
      </td>
    </tr>
  )
}
