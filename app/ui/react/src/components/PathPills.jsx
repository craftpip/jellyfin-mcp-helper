const ICONS = {
  folder: (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M1.5 4.5A1.5 1.5 0 0 1 3 3h3.2l1.6 1.6h5.2A1.5 1.5 0 0 1 14.5 6.1V11a1.5 1.5 0 0 1-1.5 1.5H3A1.5 1.5 0 0 1 1.5 11z" />
    </svg>
  ),
  season: (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M1.5 4.5A1.5 1.5 0 0 1 3 3h3.2l1.6 1.6h5.2A1.5 1.5 0 0 1 14.5 6.1V11a1.5 1.5 0 0 1-1.5 1.5H3A1.5 1.5 0 0 1 1.5 11z" />
      <circle cx="8" cy="8.9" r="1.4" />
    </svg>
  ),
  file: (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M3 1.5h6.5L13 5v9.5H3z" />
      <path d="M9.5 1.5V5H13" />
    </svg>
  ),
}

function StatusPill({ icon, label, exists, tip }) {
  return (
    <span
      className={'status-pill ' + (exists ? 'exists' : 'missing')}
      title={tip}
      aria-label={label + ': ' + tip}
    >
      <span className="mark">{exists ? '✓' : '✗'}</span>
      {ICONS[icon]}
    </span>
  )
}

export default function PathPills({ item }) {
  // Shared by ReportPanel and HistoryPage. Accept camelCase (report) and
  // snake_case (history) shapes; missing pathExists means "nothing exists yet".
  const kind = item.itemType ?? item.item_type ?? ''
  const existsStr = item.pathExists ?? item.path_exists ?? ''
  if (kind === 'series') {
    const show = existsStr.includes('Show ✓')
    const season = existsStr.includes('Season ✓')
    const file = existsStr.includes('File ✓')
    return (
      <>
        <StatusPill
          icon="folder"
          label="Show"
          exists={show}
          tip={
            show
              ? 'Main show folder exists on target'
              : 'Main show folder does not exist on target — will be created'
          }
        />
        <StatusPill
          icon="season"
          label="Season"
          exists={season}
          tip={
            season
              ? 'Season folder exists on target'
              : 'Season folder does not exist on target — will be created'
          }
        />
        <StatusPill
          icon="file"
          label="File"
          exists={file}
          tip={
            file
              ? 'File exists on target — it will be replaced'
              : 'File does not exist on target — new file will be moved in'
          }
        />
      </>
    )
  }
  const folder = existsStr.includes('Folder ✓')
  const file = existsStr.includes('File ✓')
  const folderName = kind === 'series' ? 'Show folder' : 'Movie folder'
  return (
    <>
      <StatusPill
        icon="folder"
        label="Folder"
        exists={folder}
        tip={
          folder
            ? folderName + ' exists on target'
            : folderName + ' does not exist on target — will be created'
        }
      />
      <StatusPill
        icon="file"
        label="File"
        exists={file}
        tip={
          file
            ? 'File exists on target — it will be replaced'
            : 'File does not exist on target — new file will be moved in'
        }
      />
    </>
  )
}
