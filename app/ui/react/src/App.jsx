import { useState, useEffect } from 'react'
import { useAppStore } from './store/AppStore.jsx'
import TopBar from './components/TopBar.jsx'
import Toasts from './components/Toasts.jsx'
import LogPanel from './components/LogPanel.jsx'
import ActionsPanel from './components/ActionsPanel.jsx'
import Dashboard from './components/Dashboard.jsx'
import ScanProgressPanel from './components/ScanProgressPanel.jsx'
import ReportLoadingPanel from './components/ReportLoadingPanel.jsx'
import ReportPanel from './components/ReportPanel.jsx'
import ConfirmModal from './components/ConfirmModal.jsx'
import BrowseModal from './components/BrowseModal.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import LoginScreen from './components/LoginScreen.jsx'
import SetupWizard from './components/SetupWizard.jsx'
import SettingsPage from './components/SettingsPage.jsx'
import HistoryPage from './components/HistoryPage.jsx'

export default function App() {
  const { state } = useAppStore()
  const [paletteOpen, setPaletteOpen] = useState(false)
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen(v => !v)
      }
      if (e.key === 'Escape' && paletteOpen) setPaletteOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [paletteOpen])

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

      {state.page === 'scan' && !state.rootsConfigured && <SetupWizard />}
      {state.page === 'scan' && state.rootsConfigured && (
        <>
          {!state.scanRunning && !state.reportLoading && !state.reportVisible && (
            <>
              <Dashboard />
              <ActionsPanel />
            </>
          )}
          <ScanProgressPanel progress={state.scanProgress} />
          {state.reportLoading && <ReportLoadingPanel />}
          {!state.scanRunning && !state.reportLoading && <ReportPanel />}
          <ConfirmModal />
          <BrowseModal />
        </>
      )}
      {state.page === 'settings' && <SettingsPage />}
      {state.page === 'history' && <HistoryPage />}

      {state.logsVisible && <LogPanel />}
      <Toasts />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  )
}
