import { useAppStore } from '../store/AppStore.jsx'

export default function TopBar() {
  const { state } = useAppStore()
  const cls = state.connStatus === 'connected' ? 'connected' : state.connStatus === 'error' ? 'error' : ''
  return (
    <div className="top-bar">
      <div>
        <h1>JellySort</h1>
        <div className="subtitle">Scan, review, and move download files into your media library</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <a href="/legacy/" style={{ color: '#58a6ff', textDecoration: 'none', fontSize: '0.8rem', whiteSpace: 'nowrap' }} title="Open the legacy panel">
          ← Legacy UI
        </a>
        <div className={'status' + (cls ? ' ' + cls : '')} id="connStatus">
          {state.connMessage}
        </div>
      </div>
    </div>
  )
}
