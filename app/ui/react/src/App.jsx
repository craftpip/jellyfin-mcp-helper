import { useAppStore } from './store/AppStore.jsx'
import TopBar from './components/TopBar.jsx'
import Toasts from './components/Toasts.jsx'
import LogPanel from './components/LogPanel.jsx'
import ActionsPanel from './components/ActionsPanel.jsx'
import ScanProgressPanel from './components/ScanProgressPanel.jsx'
import ReportLoadingPanel from './components/ReportLoadingPanel.jsx'
import ReportPanel from './components/ReportPanel.jsx'
import ConfirmModal from './components/ConfirmModal.jsx'
import LoginScreen from './components/LoginScreen.jsx'

export default function App() {
  const { state } = useAppStore()

  if (state.authRequired && !state.authed) {
    return (
      <>
        <LoginScreen />
        <Toasts />
      </>
    )
  }

  return (
    <>
      <TopBar />

      {!state.scanRunning && !state.reportLoading && !state.reportVisible && <ActionsPanel />}
      <ScanProgressPanel progress={state.scanProgress} />
      {state.reportLoading && <ReportLoadingPanel />}
      {!state.scanRunning && !state.reportLoading && <ReportPanel />}
      {state.logsVisible && <LogPanel />}

      <ConfirmModal />
      <Toasts />
    </>
  )
}
