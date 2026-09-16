// Confirmations for things that were written to the audit log.
//
// Every action a user records on this product lands in an append-only, hash-chained table
// with their user id against it. The toast says so explicitly — "recorded in the audit
// log" — because a user is entitled to know when their click became a permanent record,
// and because a confirmation that only says "Saved" is not informed consent.
//
// The live region is `role="status"`/`aria-live="polite"` and always mounted: a live
// region created at the same moment as its content is not announced by most screen
// readers, which is the single most common way this pattern is got wrong.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { CircleCheck, TriangleAlert, X } from 'lucide-react'

const ToastContext = createContext(null)

export function useToast() {
  const value = useContext(ToastContext)
  if (!value) throw new Error('useToast() must be used inside <ToastProvider>')
  return value
}

let nextId = 1

export function ToastProvider({ children, timeoutMs = 7000 }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) { clearTimeout(timer); timers.current.delete(id) }
  }, [])

  const push = useCallback((toast) => {
    const id = nextId++
    setToasts((list) => [...list, { id, tone: 'success', ...toast }])
    if (timeoutMs > 0 && toast.tone !== 'error') {
      timers.current.set(id, setTimeout(() => dismiss(id), timeoutMs))
    }
    return id
  }, [dismiss, timeoutMs])

  useEffect(() => {
    const map = timers.current
    return () => { for (const timer of map.values()) clearTimeout(timer) }
  }, [])

  const value = useMemo(() => ({
    push,
    dismiss,
    /** A write that is now in the audit log. Say so — do not just say "Saved". */
    audited: (message, detail) => push({ tone: 'success', message, detail, audited: true }),
    error: (message, detail) => push({ tone: 'error', message, detail }),
  }), [push, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[95] flex flex-col items-center gap-2 p-4 md:bottom-4 md:right-4 md:left-auto md:items-end"
        data-testid="toast-region"
      >
        <div role="status" aria-live="polite" aria-atomic="false" className="contents">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border px-4 py-3 shadow-lg ${
                toast.tone === 'error'
                  ? 'border-red-200 bg-white text-rag-redtx'
                  : 'border-idbi-green/30 bg-white text-idbi-green'
              }`}
            >
              {toast.tone === 'error'
                ? <TriangleAlert size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
                : <CircleCheck size={18} className="mt-0.5 shrink-0" aria-hidden="true" />}
              <div className="min-w-0 flex-1 text-sm">
                <div className="font-semibold text-slate-800">{toast.message}</div>
                {toast.detail && <div className="mt-0.5 text-xs leading-relaxed text-slate-600">{toast.detail}</div>}
                {toast.audited && (
                  <div className="mt-1 text-xs text-slate-600">
                    Recorded in the append-only audit log against your user id.
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                aria-label="Dismiss notification"
                className="rounded p-0.5 text-slate-600 transition hover:bg-slate-100 hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
              >
                <X size={15} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  )
}

export default ToastProvider
