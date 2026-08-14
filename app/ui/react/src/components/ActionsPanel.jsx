import { useAppStore } from '../store/AppStore.jsx'

export default function ActionsPanel() {
  const { state, actions } = useAppStore()
  const { scanRunning, confirmActive, reportVisible, logsVisible } = state

  if (scanRunning || reportVisible) return null

  return (
    <div className={'start-scan' + (logsVisible ? ' compact' : '')}>
      <div className="start-scan-sub">Scan your new files and organize them into your library</div>
      <button
        className={'primary btn-start' + (scanRunning ? ' scanning' : '')}
        id="btnStartScan"
        disabled={scanRunning || confirmActive}
        onClick={actions.startScan}
      >
        {scanRunning ? (
          <>
            <span className="spinner" aria-hidden="true" />
            Scanning...
          </>
        ) : (
          'Start Scan'
        )}
      </button>
    </div>
  )
}
