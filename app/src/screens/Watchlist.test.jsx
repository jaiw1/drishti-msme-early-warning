import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Watchlist from './Watchlist'
import { renderScreen, session } from '../test/render'
import { B, apiRoutes, fail, mockApi, ok, portfolio } from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = (opts) => renderScreen(<Watchlist />, { path: '/watchlist', ...opts })

// The screen makes two calls: the page of rows, and the run's roll-up for the KPI strip.
// A test that only waits for the rows leaves the second landing after the test body has
// returned, which React reports as an un-acted update. Wait for both.
// ("Red — act now" is also a band-filter option, so key off the KPI's own sub-line.)
const settled = () => screen.findByText(/exposure at risk/)

describe('Watch-list', () => {
  it('is titled for the whole book, not for one product', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByRole('heading', { name: 'Borrower Watch-list — all lending portfolios' })).toBeInTheDocument()
  })

  it('shows a loading state before anything arrives', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(screen.getByTestId('state-loading')).toBeInTheDocument()
    await settled()
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

    await settled()
    first.focus()
    await userEvent.keyboard('{ArrowDown}')
    await waitFor(() => expect(second).toHaveFocus())
    // The roving group moves its tab stop with focus; wait for that to commit too.
    await waitFor(() => expect(second).toHaveAttribute('tabindex', '0'))
  })

  it('opens the account drawer from the keyboard', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const row = await screen.findByRole('row', { name: /MSME00001/ })
    await settled()
    row.focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByRole('dialog')).toHaveAccessibleName(/MSME00001/)
    // The drawer fetches the account, its timeline and its memo; let all three land.
    await screen.findByText(/Why the model flagged this account/)
    await screen.findByText(/Early-warning memo/)
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

describe('Watch-list — counting honestly', () => {
  it('describes the server’s page when no client filter is on', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    await settled()
    expect(screen.getByText(/Showing 1–2 of 2/)).toBeInTheDocument()
  })

  it('says what it is counting once a client-side filter narrows the page', async () => {
    mockApi(apiRoutes({
      [`${B}/drishti/portfolio`]: ok(portfolio(undefined, { total: 160 })),
    }), { vi })
    render()
    await settled()
    // The search box filters the page the server already sent; the book is still 160.
    await userEvent.type(screen.getByLabelText('Search this page'), 'HOUS')
    const line = await screen.findByText(/match the/)
    expect(line).toHaveTextContent('160 accounts in the book')
    expect(line).not.toHaveTextContent('Showing 1–')
  })
})
