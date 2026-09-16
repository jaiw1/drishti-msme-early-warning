// Focus containment for modal dialogs: focus moves in on open, cycles inside while open,
// and returns to whatever opened the dialog on close. Used by every dialog in the kit
// (Dialog, IdleWarningModal, ScreenHelp) so the behaviour is identical everywhere.
//
// The subtlety that makes this a hook and not five lines: the effect must run **once per
// activation**, not once per render. Callers write `onClose={() => setOpen(false)}`, which
// is a new function on every render; an effect that depends on it tears down and sets up
// again each time the parent re-renders — and its cleanup restores focus to whatever
// opened the dialog. A user typing into the second field of a form watched their
// keystrokes vanish every time anything above them re-rendered. So the callbacks live in
// refs and the effect is keyed on `active` alone.

import { useEffect, useRef } from 'react'

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
  const onCloseRef = useRef(onClose)
  const initialRef = useRef(initialFocusRef)
  onCloseRef.current = onClose
  initialRef.current = initialFocusRef

  useEffect(() => {
    if (!active) return undefined
    const container = ref.current
    if (!container) return undefined
    const previouslyFocused = document.activeElement

    const target = initialRef.current?.current || focusableWithin(container)[0] || container
    // Deferred a tick so the dialog is painted before focus lands on it — which means a
    // fast user can have moved focus themselves before this fires. Moving it back then
    // would eat their keystrokes.
    const timer = setTimeout(() => {
      if (container.contains(document.activeElement)) return
      try { target.focus() } catch { /* jsdom detached node */ }
    }, 0)

    const onKeyDown = (event) => {
      if (event.key === 'Escape' && onCloseRef.current) {
        event.stopPropagation()
        onCloseRef.current()
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
      clearTimeout(timer)
      container.removeEventListener('keydown', onKeyDown)
      if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
        try { previouslyFocused.focus() } catch { /* the opener may be gone */ }
      }
    }
    // `ref` and `active` only: see the note at the top of the file.
  }, [ref, active])

  return undefined
}

export default useFocusTrap
