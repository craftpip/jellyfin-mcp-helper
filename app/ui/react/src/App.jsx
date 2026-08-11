import { useAppStore } from './store/AppStore.jsx'
import TopBar from './components/TopBar.jsx'
import Toasts from './components/Toasts.jsx'
import LogPanel from './components/LogPanel.jsx'
import ActionsPanel from './components/ActionsPanel.jsx'
import ScanProgressPanel from './components/ScanProgressPanel.jsx'
import ReportPanel from './components/ReportPanel.jsx'
import ConfirmModal from './components/ConfirmModal.jsx'

export default function App() {
  const { state } = useAppStore()

  return (
    <>
      <TopBar />

      <div className="panel">
        <div className="hint">
          Main flow lives here now. Start a scan, review the planned paths, then confirm the items you actually
          want to move.
        </div>
        <div className="flow">
          <div className="flow-step">
            <strong>1. Start Scan</strong>Build the current move plan from your downloads.
          </div>
          <div className="flow-step">
            <strong>2. Review Report</strong>Check target paths, whether the destination path already exists, and
            skipped items.
          </div>
          <div className="flow-step">
            <strong>3. Confirm Selected</strong>Move only the checked items and watch progress live.
          </div>
        </div>
      </div>

      <ActionsPanel />
      <ScanProgressPanel progress={state.scanProgress} />
      <ReportPanel />
      <LogPanel />

      <ConfirmModal />
      <Toasts />
    </>
  )
}
