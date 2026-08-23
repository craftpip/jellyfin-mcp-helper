// Generic poll helper — keeps AppStore lean. No DOM, pure timer logic.
import { useRef, useCallback } from 'react'

export function usePoll(fn, intervalMs = 2000) {
  const timer = useRef(null)
  const active = useRef(false)

  const start = useCallback(() => {
    active.current = true
    const tick = async () => {
      if (!active.current) return
      try {
        await fn()
      } catch {}
      if (active.current) {
        timer.current = setTimeout(tick, intervalMs)
      }
    }
    // clear any previous
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(tick, intervalMs)
  }, [fn, intervalMs])

  const stop = useCallback(() => {
    active.current = false
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  const isActive = useCallback(() => active.current, [])

  return { start, stop, isActive }
}
