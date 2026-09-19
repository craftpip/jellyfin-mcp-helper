import { useEffect, useRef, useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'
import { apiGet } from '../api/apiClient.js'

export default function BrowseModal() {
  const { state } = useAppStore()
  const browse = state.browseModal
  if (!browse || !browse.open) return null

  return <BrowseView confirmId={browse.confirmId} />
}

function BrowseView({ confirmId }) {
  const { state, actions } = useAppStore()
  const item = state.currentItems.find((i) => i.confirmId === confirmId)
  const isSeries = item?.itemType === 'series'

  return (
    <FolderPicker
      title={item ? item.title : null}
      suspectNote={item?.suspect ? ' — flagged as suspicious' : ''}
      correctionNote={item?.correctionNote ? ' — ' + item.correctionNote : ''}
      showReclassifyOption={isSeries}
      showApplyToGroupOption={!!item}
      onPick={(directory, opts) =>
        actions.retargetItem(
          confirmId,
          directory,
          !!opts?.applyToGroup,
          !!opts?.reclassifyAsMovie
        )
      }
      onClose={() => actions.closeBrowse()}
    />
  )
}

export function FolderPicker({ title, suspectNote, correctionNote, showReclassifyOption, showApplyToGroupOption, onPick, onClose }) {
  const [roots, setRoots] = useState([])
  const [cwd, setCwd] = useState('')
  const [root, setRoot] = useState('')
  const [entries, setEntries] = useState([])
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [applyToGroup, setApplyToGroup] = useState(false)
  const [reclassifyAsMovie, setReclassifyAsMovie] = useState(false)
  const didInit = useRef(false)

  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCloseRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (didInit.current) return
    didInit.current = true
    apiGet('/browse/roots')
      .then((res) => {
        const list = res.roots || []
        setRoots(list)
        setFiles([])
        setEntries(
          list.map((r) => ({
            name: r.path,
            path: r.path,
            isDir: true,
            videoCount: 0,
            seasonNumber: null,
          }))
        )
      })
      .catch((e) => setError('Failed to load libraries: ' + e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function load(path) {
    setLoading(true)
    setError('')
    try {
      const res = await apiGet('/browse?path=' + encodeURIComponent(path))
      setCwd(res.path)
      setRoot(res.root || '')
      setEntries(res.entries || [])
      setFiles(res.files || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function goUp() {
    if (entries.parent) {
      load(entries.parent)
      return
    }
    setCwd('')
    setRoot('')
    setFiles([])
    setEntries(
      roots.map((r) => ({
        name: r.path,
        path: r.path,
        isDir: true,
        videoCount: 0,
        seasonNumber: null,
      }))
    )
  }

  async function doSearch(q) {
    const text = (q || '').trim()
    if (!text) {
      setResults([])
      setSearched(false)
      return
    }
    setSearching(true)
    setSearched(false)
    setError('')
    try {
      const res = await apiGet('/browse/search?q=' + encodeURIComponent(text))
      setResults(res.results || [])
      setSearched(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setSearching(false)
    }
  }

  function pickSearchResult(path) {
    setQuery('')
    setResults([])
    setSearched(false)
    load(path)
  }

  function select() {
    if (!cwd) return
    onPick(cwd, { applyToGroup, reclassifyAsMovie })
    onClose()
  }

  const breadcrumb = cwd.split('/').filter(Boolean)
  const targetCount = entries.reduce((s, e) => s + (e.videoCount || 0), 0)
  const atTopLevel = !cwd

  return (
    <div className="modal-overlay" id="browseModal">
      <div className="modal browse-modal" role="dialog" aria-modal="true" aria-labelledby="browseModalTitle">
        <h3 id="browseModalTitle">Choose target folder</h3>
        {title && (
          <div className="hint" style={{ marginBottom: '8px' }}>
            {title}
            {suspectNote}
            {correctionNote}
          </div>
        )}

        <div className="browse-search">
          <input
            type="text"
            id="browseSearch"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') doSearch(query)
            }}
            placeholder="Search existing folders by name..."
          />
          <button className="small browse-search-btn" onClick={() => doSearch(query)}>
            Search
          </button>
          {searching && <span className="hint">searching…</span>}
        </div>

        {results.length > 0 && (
          <div className="browse-results" id="browseSearchResults">
            {results.map((r, i) => (
              <button
                key={r.path}
                className="browse-row search-hit"
                onClick={() => pickSearchResult(r.path)}
              >
                <span className="browse-row-main">
                  {r.name}
                  {r.seasonNumber != null && <span className="badge">S{r.seasonNumber}</span>}
                </span>
                <span className="browse-row-sub">{r.path}</span>
              </button>
            ))}
          </div>
        )}

        {results.length === 0 && searched && !error && (
          <div className="browse-results" id="browseNoResults">
            No folders match &quot;{query.trim()}&quot;. Check the spelling or try a different name.
          </div>
        )}

        {results.length === 0 && !searched && (
        <div className="browse-crumbs" id="browseCrumbs">
          {!atTopLevel && (
            <button className="browse-crumb" onClick={goUp} title="All libraries">
              All libraries
            </button>
          )}
          {breadcrumb.map((part, i) => (
            <span key={i}>
              <button className="browse-crumb" onClick={() => load('/' + breadcrumb.slice(0, i + 1).join('/'))}>
                {part}
              </button>
              {i < breadcrumb.length - 1 && <span className="browse-sep">/</span>}
            </span>
          ))}
        </div>
        )}

        {error && <div className="browse-error">{error}</div>}

        {results.length === 0 && !searched && (
        <div className="browse-list" id="browseList">
          {loading && <div className="hint">Loading…</div>}
          {!loading && !atTopLevel && (
            <button className="browse-row" onClick={goUp}>
              <span className="browse-row-main">..</span>
            </button>
          )}
          {!loading &&
            entries.map((e) => (
              <button key={e.path} className="browse-row" onClick={() => load(e.path)}>
                <span className="browse-row-main">
                  {e.name}
                  {e.seasonNumber != null && <span className="badge">S{e.seasonNumber}</span>}
                  {e.videoCount > 0 && (
                    <span className="browse-count">
                      {e.seasonNumber != null
                        ? e.videoCount + ' file(s)'
                        : e.videoCount + ' subfolder(s)'}
                    </span>
                  )}
                </span>
                <span className="browse-row-sub">{e.path}</span>
              </button>
            ))}
          {!loading &&
            files.map((f) => (
              <div
                key={f.path}
                className="browse-row browse-file"
                aria-disabled="true"
                title={f.path}
              >
                <span className="browse-row-main browse-file-name">{f.name}</span>
              </div>
            ))}
          {!loading && entries.length === 0 && files.length === 0 && <div className="hint">No folders here.</div>}
        </div>
        )}

        {(showReclassifyOption || showApplyToGroupOption) && (
          <div className="browse-options">
            {showReclassifyOption && (
              <label className="chk-label">
                <input
                  type="checkbox"
                  checked={reclassifyAsMovie}
                  onChange={(e) => {
                    setReclassifyAsMovie(e.target.checked)
                    if (e.target.checked) setApplyToGroup(false)
                  }}
                />
                <span className="chk-text">Treat as movie (franchise movie folder)</span>
              </label>
            )}
            {!reclassifyAsMovie && showApplyToGroupOption && (
              <label className="chk-label">
                <input
                  type="checkbox"
                  checked={applyToGroup}
                  onChange={(e) => setApplyToGroup(e.target.checked)}
                />
                <span className="chk-text">Apply to all items in this group</span>
              </label>
            )}
          </div>
        )}

        <div className="browse-footer">
          <div className="hint browse-target" id="browseTarget">
            {cwd ? 'Target: ' + cwd : 'Choose a folder above'}
            {targetCount > 0 && ' (' + targetCount + ' files)'}
          </div>
          <div className="browse-actions">
            <button className="small" onClick={onClose}>
              Cancel
            </button>
            <button className="primary small" disabled={!cwd || loading} onClick={select}>
              Select this folder
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
