import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Watchlist from './Watchlist'
import { renderScreen, session } from '../test/render'
import { B, apiRoutes, fail, mockApi, ok, portfolio } from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = (opts) => renderScreen(<Watchlist />, { path: '/watchlist', ...opts })

describe('Watch-list', () => {
  it('is titled for the whole book, not for one product', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByRole('heading', { name: 'Borrower Watch-list — all lending portfolios' })).toBeInTheDocument()
  })

  it('shows a loading state before anything arrives', () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(screen.getByTestId('state-loading')).toBeInTheDocument()
  })

  it('shows the shared error state, with the request id, when the API fails', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/portfolio`]: fail(500, { code: 'internal_error', message: 'Boom.' }) }), { vi })
    render()
    expect(await screen.findByTestId('state-error')).toHaveTextContent('Could not load the watch-list')
    expect(screen.getByTestId('state-error')).toHaveTextContent('req-test')
  })

  it('shows an empty state — not a blank table — when the run has no rows', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/portfolio`]: ok(portfolio([])) }), { vi })
    render()
    expect(await screen.findByTestId('state-empty')).toHaveTextContent('No accounts match these filters')
  })

  it('tells a scoped officer that the server, not the screen, shortened the list', async () => {
    mockApi(apiRoutes({
      [`${B}/drishti/portfolio`]: ok(portfolio(undefined, { scope: ['MSME-CC', 'MSME-TL', 'LAP'] })),
    }), { vi })
    render({ user: session('credit_officer') })
    expect(await screen.findByText(/You are scoped to/)).toHaveTextContent('MSME-CC, MSME-TL, LAP')
  })

  it('shows both bands when the recomputed one differs from the published one', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const row = await screen.findByRole('row', { name: /MSME00001/ })
    expect(within(row).getByText('Red')).toBeInTheDocument()
    expect(within(row).getByText('amber')).toBeInTheDocument() // the published band
    expect(screen.getByText(/recomputed against the thresholds in force right now/)).toBeInTheDocument()
  })

  it('sends only the contract’s allowlisted filters to the server', async () => {
    const api = mockApi(apiRoutes(), { vi })
    render()
    await screen.findByRole('row', { name: /MSME00001/ })
    await userEvent.selectOptions(screen.getByLabelText('Portfolio'), 'Housing')

    await waitFor(() => {
      const last = api.calls.filter((c) => c.path === `${B}/drishti/portfolio`).at(-1)
      expect(last.url).toContain('portfolio=Housing')
      expect(last.url).toContain('sort=pd')
    })
    // DPD and ticket band are derived client-side; sending them would be a query the
    // server silently ignores.
    const last = api.calls.filter((c) => c.path === `${B}/drishti/portfolio`).at(-1)
    expect(last.url).not.toContain('dpd=')
    expect(last.url).not.toContain('ticket=')
  })

  it('marks the sorted column with aria-sort so it is announced', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    await screen.findByRole('row', { name: /MSME00001/ })
    expect(screen.getByRole('columnheader', { name: /PD \(12-mo\)/ })).toHaveAttribute('aria-sort', 'descending')
    expect(screen.getByRole('columnheader', { name: /Exposure/ })).toHaveAttribute('aria-sort', 'none')
  })

  it('gives the table one tab stop and moves between rows with the arrow keys', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const first = await screen.findByRole('row', { name: /MSME00001/ })
    const second = screen.getByRole('row', { name: /HOUS00007/ })
    expect(first).toHaveAttribute('tabindex', '0')
    expect(second).toHaveAttribute('tabindex', '-1')

    first.focus()
    await userEvent.keyboard('{ArrowDown}')
    await waitFor(() => expect(second).toHaveFocus())
  })

  it('opens the account drawer from the keyboard', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const row = await screen.findByRole('row', { name: /MSME00001/ })
    row.focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByRole('dialog')).toHaveAccessibleName(/MSME00001/)
  })

  it('reads the frozen snapshot, and says so, when there is no backend', async () => {
    const snapshot = {
      meta: { reference_month: '2026-09', n_accounts_scored: 1, provenance: { model: 'SIMULATED' } },
      portfolio_summary: { red: 1, amber: 0, green: 0, red_thr: 0.5, amber_thr: 0.2, total_accounts: 1, exposure_at_risk: 100 },
      portfolio: [{ account_id: 'SNAP00001', portfolio: 'Agri', pd: 0.8, bucket: 'red', sanctioned: 100, reasons: ['x'], channels_present: ['repayment'] }],
      metrics: {}, timelines: {}, memos: {}, rigor: {},
    }
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (String(url).endsWith('demo_data.json')) {
        return { ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => snapshot }
      }
      throw new Error(`unexpected fetch ${url}`)
    }))
    render({ mode: 'static' })
    expect(await screen.findByRole('row', { name: /SNAP00001/ })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Simulated' }).length).toBeGreaterThan(0)
  })
})
