import { dismissToast, useToasts } from '../stores/toasts'
import './Toaster.css'

/** Shows messages passed to pushFlash() in the top-right corner; click a message to close it. */
export default function Toaster() {
  const toasts = useToasts()
  if (!toasts.length) {
    return null
  }
  return (
    <div className="app-toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        // A div, not a button: the global button styles in app.css/style.css would restyle it.
        <div
          key={toast.id}
          className={`app-toast app-toast-${toast.category}`}
          title="点击关闭"
          onClick={() => dismissToast(toast.id)}
        >
          {toast.message}
        </div>
      ))}
    </div>
  )
}
