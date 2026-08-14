import { useState } from 'react'
import { useAppStore } from '../store/AppStore.jsx'

export default function LoginScreen() {
  const { actions } = useAppStore()
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function onSubmit(e) {
    e.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setError('')
    try {
      await actions.login(password)
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <h2 className="login-title">JellySort</h2>
        <p className="login-subtitle">This panel is protected. Enter the panel password to continue.</p>
        <form onSubmit={onSubmit}>
          <input
            type="password"
            autoFocus
            placeholder="Panel password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <div className="login-error">{error}</div>}
          <button type="submit" className="primary login-submit" disabled={busy || !password}>
            {busy ? 'Logging in...' : 'Log in'}
          </button>
        </form>
      </div>
    </div>
  )
}
