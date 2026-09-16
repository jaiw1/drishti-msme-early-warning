// Focus containment for modal dialogs: focus moves in on open, cycles inside while open,
// and returns to whatever opened the dialog on close. Used by every dialog in the kit
// (IdleWarningModal, ScreenHelp) so the behaviour is identical everywhere.

import { useEffect } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function focusableWithin(node) {
  if (!node) return []
  return Array.from(node.querySelectorAll(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement || el.getClientRects().length > 0,
  )
}

export function useFocusTrap(ref, { active = true, onClose, initialFocusRef } = {}) {
  useEffect(() => {
    if (!active) return undefined
    const container = ref.current
    if (!container) return undefined
    const previouslyFocused = document.activeElement

    const target = initialFocusRef?.current || focusableWithin(container)[0] || container
    // A microtask, so the dialog is painted before focus lands on it.
    const raf = setTimeout(() => { try { target.focus() } catch { /* jsdom detached node */ } }, 0)

    const onKeyDown = (event) => {
      if (event.key === 'Escape' && onClose) {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusableWithin(container)
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    container.addEventListener('keydown', onKeyDown)
    return () => {
      clearTimeout(raf)
      container.removeEventListener('keydown', onKeyDown)
      if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
        try { previouslyFocused.focus() } catch { /* the opener may be gone */ }
      }
    }
  }, [ref, active, onClose, initialFocusRef])
}

export default useFocusTrap
