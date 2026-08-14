import { useEffect, useRef } from 'react'
import { useAppStore } from '../store/AppStore.jsx'

export default function LogPanel() {
  const { state } = useAppStore()
  const ref = useRef(null)

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [state.logEntries.length])

  return (
    <div className="panel log-panel">
      <h2>Log</h2>
      <div className="log" ref={ref}>
        {state.logEntries.map((e, i) => (
          <div key={i} className={e.type}>
            {e.msg}
          </div>
        ))}
      </div>
    </div>
  )
}
