import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ScreenHelp from './ScreenHelp'
import { HELP } from '../help'

describe('ScreenHelp', () => {
  it('renders nothing for a screen with no help entry', () => {
    const { container } = render(<ScreenHelp screen="nope" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('opens a labelled dialog with the copy for that screen', async () => {
    const user = userEvent.setup()
    render(<ScreenHelp screen="watchlist" />)

    const trigger = screen.getByRole('button', { name: 'Help' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await user.click(trigger)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleName(HELP.watchlist.title)
    expect(dialog).toHaveTextContent(HELP.watchlist.sections[0].heading)
    expect(dialog).toHaveTextContent(HELP.watchlist.caveat)
  })

  it('closes on Escape and gives focus back to the trigger', async () => {
    const user = userEvent.setup()
    render(<ScreenHelp screen="model" />)
    const trigger = screen.getByRole('button', { name: 'Help' })

    await user.click(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('has an entry for every screen the cockpit links to', () => {
    for (const key of ['watchlist', 'risk', 'model', 'real', 'sources', 'login', 'admin']) {
      expect(HELP[key]).toBeTruthy()
      expect(HELP[key].summary.length).toBeGreaterThan(30)
    }
  })
})
