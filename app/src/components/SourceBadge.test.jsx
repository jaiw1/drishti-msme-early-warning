import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SourceBadge, { SOURCE, SOURCES, normaliseSource } from './SourceBadge'

describe('normaliseSource', () => {
  it.each([
    ['BANK_API', false, SOURCE.BANK_API],
    ['BANK_API', true, SOURCE.BANK_API_SANDBOX],
    ['BANK_API+sandbox_fixture', false, SOURCE.BANK_API_SANDBOX],
    ['bank_api', false, SOURCE.BANK_API],
    ['SIMULATED', false, SOURCE.SIMULATED],
    ['FIXTURE', false, SOURCE.FIXTURE],
    ['NOT_COLLECTED', false, SOURCE.NOT_COLLECTED],
    [undefined, false, SOURCE.NOT_COLLECTED],
    ['something-else', false, SOURCE.NOT_COLLECTED],
  ])('%s (sandbox=%s) -> %s', (value, sandbox, expected) => {
    expect(normaliseSource(value, sandbox)).toBe(expected)
  })

  it.each([
    ['BANK_API', false, false, SOURCE.BANK_API],
    ['BANK_API', false, true, SOURCE.BANK_API_CACHED],
    ['BANK_API', true, true, SOURCE.BANK_API_CACHED],
    ['BANK_API+cached', false, false, SOURCE.BANK_API_CACHED],
    ['bank_api_cached', false, false, SOURCE.BANK_API_CACHED],
  ])('%s (sandbox=%s, cached=%s) -> %s', (value, sandbox, cached, expected) => {
    expect(normaliseSource(value, sandbox, cached)).toBe(expected)
  })

  it('has copy for all six provenance states the plan requires', () => {
    expect(Object.keys(SOURCES)).toEqual([
      'BANK_API', 'BANK_API+sandbox_fixture', 'BANK_API+cached', 'SIMULATED', 'FIXTURE', 'NOT_COLLECTED',
    ])
    for (const spec of Object.values(SOURCES)) {
      expect(spec.description.length).toBeGreaterThan(30)
    }
  })
})

describe('SourceBadge', () => {
  it('labels the source visibly', () => {
    render(<SourceBadge source={SOURCE.SIMULATED} />)
    expect(screen.getByRole('button')).toHaveTextContent('Simulated')
  })

  it('keeps the sandbox caveat distinct from a real bank value', () => {
    const { rerender } = render(<SourceBadge source="BANK_API" />)
    expect(screen.getByRole('button')).toHaveTextContent('Bank API')
    expect(screen.getByRole('button')).not.toHaveTextContent('sandbox')

    rerender(<SourceBadge source="BANK_API" sandbox />)
    expect(screen.getByRole('button')).toHaveTextContent('Bank API · sandbox')
  })

  it('renders the cached-reuse caveat distinctly, and never as "not collected"', () => {
    render(<SourceBadge source="BANK_API" cached />)
    expect(screen.getByRole('button')).toHaveTextContent('Bank API · last good pull')
    expect(screen.getByRole('button')).not.toHaveTextContent('Not collected')
  })

  it('describes itself with a tooltip that is hidden until hover or focus', async () => {
    const user = userEvent.setup()
    render(<SourceBadge source={SOURCE.FIXTURE} />)

    const trigger = screen.getByRole('button')
    const tooltipId = trigger.getAttribute('aria-describedby')
    expect(tooltipId).toBeTruthy()
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    await user.tab()
    expect(trigger).toHaveFocus()
    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toHaveAttribute('id', tooltipId)
    expect(tooltip).toHaveTextContent('replayed from disk')
  })

  it('appends per-field detail to the explanation', async () => {
    const user = userEvent.setup()
    render(<SourceBadge source="BANK_API" sandbox detail="API 402, pulled 16 Sep 2026." />)
    await user.tab()
    expect(screen.getByRole('tooltip')).toHaveTextContent('API 402, pulled 16 Sep 2026.')
  })

  it('keeps an accessible name in the icon-only form used in dense tables', () => {
    render(<SourceBadge source={SOURCE.NOT_COLLECTED} iconOnly />)
    expect(screen.getByRole('button', { name: 'Not collected' })).toBeInTheDocument()
  })
})
