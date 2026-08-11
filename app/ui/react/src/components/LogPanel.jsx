import { useEffect, useRef } from 'react'
import { useAppStore } from '../store/AppStore.jsx'

export default function LogPanel() {
  const { state } = useAppStore()
  const ref = useRef(null)

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [state.logEntries.length])

  return (
    <details className="panel log-panel">
      <summary>Log</summary>
      <div className="log" ref={ref} style={{ marginTop: '10px' }}>
        {state.logEntries.map((e, i) => (
          <div key={i} className={e.type}>
            {e.msg}
          </div>
        ))}
      </div>
    </details>
  )
}
