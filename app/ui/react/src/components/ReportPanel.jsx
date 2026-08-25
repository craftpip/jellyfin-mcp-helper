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
  ['suspect', 'Suspect'],
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
    suspect: actionable.filter((i) => i.suspect).length,
  }
  const hasItems = actionable.length > 0
  const hasSkippedOnly = !hasItems && skipped.length > 0
  const skippedSize = skipped.reduce((s, i) => s + (Number(i.fileSize) || 0), 0)
  const allExpanded = hasItems && reportGroups.length > 0 && expandedGroups.length === reportGroups.length

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
    selectionSummary = '0 of 0 visible (of ' + actionable.length + ' total)'
  } else if (hasSkippedOnly) {
    selectionSummary = skipped.length + ' skipped — nothing to move right now'
  } else {
    selectionSummary = 'No report items loaded yet.'
  }

  const summary = reportSummary || {}

  return (
    <>
      <div id="reportPanel" style={{ background: 'transparent', border: 'none', padding: 0, boxShadow: 'none' }}>
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
        <div className="search-bar" style={{ marginLeft: 8, maxWidth: 260, flex: '0 1 240px', minWidth: 180, marginBottom: 0 }}>
          <input
            type="text"
            id="filterInput"
            value={query}
            onChange={(e) => actions.setSearchQuery(e.target.value)}
            placeholder="Search by title, path..."
            style={{ borderRadius: 999 }}
          />
          {query && (
            <button className="small" onClick={() => actions.setSearchQuery('')} title="Clear search" style={{ borderRadius: 999 }}>
              Clear
            </button>
          )}
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

      <div className="report-toolbar">
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="hint" id="selectionSummary" style={{ display: 'flex', alignItems: 'center', minHeight: 28 }}>
            {selectionSummary}
          </div>
          {hasItems && (
            <div className="filter-chips" id="filterChips" style={{ margin: 0, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              {FILTER_DEFS.map(([k, label]) => (
                <button
                  key={k}
                  className={'filter-chip' + (currentFilter === k ? ' active' : '')}
                  onClick={() => actions.setFilter(k)}
                >
                  {currentFilter === k ? '✓ ' : ''}{label} <span className="chip-count">{counts[k]}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {hasItems && (
          <div className="report-actions" style={{ marginLeft: 'auto' }}>
            <button className="small" onClick={() => actions.toggleAllGroups(!allExpanded)}>
              {allExpanded ? 'Collapse all' : 'Expand all'}
            </button>
          </div>
        )}
      </div>
    </div>

      <div id="reportItems" style={{ marginTop: 12 }}>
        {reportGroups.length === 0 && hasItems && (
          <div style={{ color: '#9aa4ab' }}>No items to review.</div>
        )}
        {reportGroups.map((group, gi) => {
          const gid = 'group-' + gi
          const expanded = expandedGroups.includes(gid)
          // Group-level filtering: show the whole group if any item matches the query+filter
          const groupMatches = group.items.some((item) => matchesFilter(item, query, currentFilter))
          if (!groupMatches) return null
          const visibleItems = group.items
          const matchedIds = new Set(group.items.filter((item) => matchesFilter(item, query, currentFilter)).map((i) => i.confirmId))
          return (
            <ReportGroup
              key={gid}
              gid={gid}
              gi={gi}
              group={group}
              expanded={expanded}
              visibleItems={visibleItems}
              matchedIds={matchedIds}
              query={query}
              filter={currentFilter}
            />
          )
        })}
      </div>
    </>
  )
}

function ReportGroup({ gid, gi, group, expanded, visibleItems, matchedIds, query, filter }) {
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
          <label className="chk-label" onClick={(e) => e.stopPropagation()} style={{ userSelect: 'none', WebkitUserSelect: 'none', cursor: 'pointer' }}>
            <input
              type="checkbox"
              className="group-select-all"
              checked={allChecked}
              onChange={(e) => actions.toggleGroupSelect(gi, e.target.checked)}
              style={{ cursor: 'pointer' }}
            />
            <span className="chk-text" style={{ userSelect: 'none', WebkitUserSelect: 'none' }}>{group.title}</span>
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
            {visibleItems.map((item) => {
              const isMatched = matchedIds ? matchedIds.has(item.confirmId) : true
              const shouldHighlight = isMatched && (filter !== 'all' || (query && query.trim() !== ''))
              return <ReportRow key={item.confirmId} item={item} isSeries={isSeries} query={query} group={group} isHighlighted={shouldHighlight} />
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function ReportRow({ item, isSeries, query, group, isHighlighted }) {
  const { state, actions } = useAppStore()
  const selected = state.selectedIds.includes(item.confirmId)
  const liveTarget = item._liveTarget || item.targetPath
  const groupSize = group ? group.items.length : 0
  const showLink = groupSize > 1
  const isLinked = item._linked !== false

  if (item.action === 'skip') {
    return (
      <tr className={"row-skipped" + (isHighlighted ? " row-highlight" : "")} style={isHighlighted ? { background: 'rgba(232,179,75,0.14)', outline: '1px solid rgba(232,179,75,0.35)', outlineOffset: '-1px' } : undefined}>
        <td style={{ cursor: 'pointer', userSelect: 'none', WebkitUserSelect: 'none' }} onClick={(e) => { if (e.target.tagName.toLowerCase() === 'input') return; actions.selectItem(item.confirmId, !selected) }}>
          <input
            type="checkbox"
            className="item-check skip-check"
            checked={selected}
            onChange={(e) => actions.selectItem(item.confirmId, e.target.checked)}
            onClick={(e) => e.stopPropagation()}
            style={{ cursor: 'pointer' }}
          />
        </td>
        <td style={{ cursor: 'pointer', userSelect: 'none', WebkitUserSelect: 'none' }} onClick={() => actions.selectItem(item.confirmId, !selected)}>
          <div className="action-cell" style={{ userSelect: 'none', WebkitUserSelect: 'none' }}>
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
            style={{ marginRight: 8 }}
          >
            Delete
          </button>
        </td>
      </tr>
    )
  }

  const actionLabel = item.action === 'replace' ? 'Existing' : 'New'
  return (
    <tr data-title={item.title.toLowerCase()} data-action={item.action} data-fileexists={item.fileExists ? 'true' : 'false'} className={isHighlighted ? "row-highlight" : undefined} style={isHighlighted ? { background: 'rgba(232,179,75,0.14)', outline: '1px solid rgba(232,179,75,0.35)', outlineOffset: '-1px' } : undefined}>
      <td style={{ cursor: 'pointer', userSelect: 'none', WebkitUserSelect: 'none' }} onClick={(e) => { if (e.target.tagName.toLowerCase() === 'input') return; actions.selectItem(item.confirmId, !selected) }}>
        <input
          type="checkbox"
          className="item-check"
          checked={selected}
          onChange={(e) => actions.selectItem(item.confirmId, e.target.checked)}
          onClick={(e) => e.stopPropagation()}
          style={{ cursor: 'pointer' }}
        />
      </td>
      <td style={{ cursor: 'pointer', userSelect: 'none', WebkitUserSelect: 'none' }} onClick={() => actions.selectItem(item.confirmId, !selected)}>
        <div className="action-cell" style={{ userSelect: 'none', WebkitUserSelect: 'none' }}>
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
              style={{ flex: 1, minWidth: 0 }}
            />
            {showLink && (
              <button
                className={'small link-toggle' + (isLinked ? ' active' : '')}
                onClick={() => actions.toggleLink(item._idx)}
                title={isLinked ? 'Link enabled — edits sync within group (click to unlink)' : 'Link disabled — editing freely (click to link)'}
                aria-label={isLinked ? 'Unlink this file' : 'Link this file'}
                aria-pressed={isLinked}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                  width: 28,
                  height: 29,
                  minWidth: 28,
                  lineHeight: 1,
                  borderColor: isLinked ? 'var(--jf-accent, #00a4dc)' : undefined,
                  background: isLinked ? 'rgba(0,164,220,0.15)' : undefined,
                }}
              >
                {isLinked ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ display: 'block' }}>
                    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ display: 'block' }}>
                    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                    <line x1="2" y1="2" x2="22" y2="22" />
                  </svg>
                )}
              </button>
            )}
          </div>
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
          style={{ marginRight: 8 }}
        >
          Delete
        </button>
      </td>
    </tr>
  )
}
