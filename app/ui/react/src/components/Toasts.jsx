import { useAppStore } from '../store/AppStore.jsx'

export default function Toasts() {
  const { state } = useAppStore()
  return (
    <>
      {state.toasts.map((t) => (
        <div key={t.id} className={'toast ' + t.type} role="status">
          {t.msg}
        </div>
      ))}
    </>
  )
}
