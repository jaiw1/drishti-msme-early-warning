import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import useFocusTrap from './useFocusTrap'

afterEach(() => vi.unstubAllGlobals())

function Harness() {
  const [open, setOpen] = useState(false)
  const panel = useRef(null)
  const first = useRef(null)
  useFocusTrap(panel, { active: open, onClose: () => setOpen(false), initialFocusRef: first })
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      {open && (
        <div ref={panel} role="dialog" aria-modal="true" aria-label="Test dialog" tabIndex={-1}>
          <label htmlFor="a">First</label>
          <input id="a" ref={first} />
          <label htmlFor="b">Second</label>
          <input id="b" />
        </div>
      )}
    </>
  )
}

describe('useFocusTrap', () => {
  it('moves focus into the dialog when it opens', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    await waitFor(() => expect(screen.getByLabelText('First')).toHaveFocus())
  })

  it('does not yank focus back from a field the user already reached', async () => {
    // The deferred focus fires a tick after open. If the user got to the second field
    // first — which is exactly what happens on a slow machine — pulling focus back to the
    // first one silently eats everything they type.
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    const second = screen.getByLabelText('Second')
    second.focus()
    await userEvent.type(second, 'hello')

    await waitFor(() => expect(second).toHaveValue('hello'))
    expect(screen.getByLabelText('First')).toHaveValue('')
  })

  it('returns focus to whatever opened it', async () => {
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Open' })
    await userEvent.click(opener)
    await waitFor(() => expect(screen.getByLabelText('First')).toHaveFocus())
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(opener).toHaveFocus())
  })

  // Tab cycling is deliberately NOT tested here. `focusableWithin` filters on layout
  // (`offsetParent`, `getClientRects`) to skip hidden controls, and jsdom reports every
  // element as having no layout at all — so the filter returns one item and the test would
  // be asserting jsdom's behaviour, not the app's. The real cycle is covered in e2e,
  // against a real browser.
})

describe('useFocusTrap — re-render safety', () => {
  function Rerendering() {
    const [open, setOpen] = useState(false)
    const [, bump] = useState(0)
    const panel = useRef(null)
    const first = useRef(null)
    // A new onClose identity on every render, which is what every caller in this app
    // actually writes.
    useFocusTrap(panel, { active: open, onClose: () => setOpen(false), initialFocusRef: first })
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>Open</button>
        <button type="button" onClick={() => bump((n) => n + 1)}>Re-render parent</button>
        {open && (
          <div ref={panel} role="dialog" aria-modal="true" aria-label="Test dialog" tabIndex={-1}>
            <label htmlFor="a">First</label>
            <input id="a" ref={first} />
            <label htmlFor="b">Second</label>
            <input id="b" />
          </div>
        )}
      </>
    )
  }

  it('keeps focus where the user put it when the parent re-renders', async () => {
    render(<Rerendering />)
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))
    const second = screen.getByLabelText('Second')
    second.focus()
    await userEvent.type(second, 'abc')

    // An effect keyed on onClose identity would tear down here, and its cleanup would
    // restore focus to the Open button — losing everything typed afterwards.
    await userEvent.click(screen.getByRole('button', { name: 'Re-render parent' }))
    second.focus()
    await userEvent.type(second, 'def')

    expect(second).toHaveValue('abcdef')
    expect(screen.getByLabelText('First')).toHaveValue('')
  })
})
