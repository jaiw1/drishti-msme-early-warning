// The one modal in this app.
//
// `role="dialog" aria-modal="true"` with a labelled heading, focus moved in on open and
// returned to the opener on close, Escape to dismiss, Tab cycling inside, and the page
// behind it inert to a screen reader. Every confirmation, drawer and prompt uses it, so
// there is exactly one implementation to get right.

import { useId, useRef } from 'react'
import { X } from 'lucide-react'
import useFocusTrap from '../lib/useFocusTrap'

export default function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  variant = 'center',
  initialFocusRef,
  closeLabel = 'Close',
  testId = 'dialog',
}) {
  const panelRef = useRef(null)
  const fallbackCloseRef = useRef(null)
  const titleId = useId()
  const descriptionId = useId()

  useFocusTrap(panelRef, {
    active: open,
    onClose,
    initialFocusRef: initialFocusRef || fallbackCloseRef,
  })

  if (!open) return null

  const widths = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', drawer: 'max-w-[760px]' }
  const isDrawer = variant === 'drawer'

  return (
    <div
      className={`fixed inset-0 z-[80] flex ${isDrawer ? 'justify-end' : 'items-center justify-center p-4'}`}
      data-testid={testId}
    >
      <div className="absolute inset-0 bg-slate-900/50" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`scroll-thin relative flex w-full flex-col overflow-y-auto bg-white shadow-2xl ${
          isDrawer ? `h-full ${widths.drawer}` : `max-h-[90vh] rounded-2xl ${widths[size] || widths.md}`
        }`}
      >
        <div className="sticky top-0 z-10 flex items-start gap-4 border-b border-slate-200 bg-white px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-lg font-extrabold text-slate-900">{title}</h2>
            {description && (
              <p id={descriptionId} className="mt-0.5 text-sm leading-relaxed text-slate-600">{description}</p>
            )}
          </div>
          <button
            ref={fallbackCloseRef}
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            className="rounded-lg p-1 text-slate-600 transition hover:bg-slate-100 hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 px-5 py-5">{children}</div>

        {footer && (
          <div className="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 bg-white px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
