import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import PortfolioRiskScreen from './PortfolioRiskScreen'
import { renderScreen } from '../test/render'
import { B, apiRoutes, envelope, fail, metrics, mockApi, ok, portfolio } from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = (opts) => renderScreen(<PortfolioRiskScreen />, { path: '/risk', ...opts })

describe('Portfolio risk', () => {
  it('groups the book by lending portfolio, not only by sector and segment', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByRole('heading', { name: /by lending portfolio/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'By sector' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'By segment' })).toBeInTheDocument()
  })

  it('carries each portfolio’s own Red-band precision, with its interval and its n', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const heading = await screen.findByText('Red-band precision, per portfolio')
    const cards = heading.nextElementSibling
    const msme = within(cards).getByText('MSME-CC').parentElement
    expect(msme).toHaveTextContent('100.0%')
    expect(msme).toHaveTextContent('95% CI 51.0%–100.0%')
    expect(msme).toHaveTextContent('4 of 4')
    expect(within(cards).getByText('Housing').parentElement).toHaveTextContent('75.0%')
  })

  it('says a portfolio’s precision is not reported rather than inventing one', async () => {
    const m = metrics()
    delete m.data.metrics.rank_order.by_portfolio['MSME-CC'].red_band_precision_8m
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(m) }), { vi })
    render()
    const heading = await screen.findByText('Red-band precision, per portfolio')
    expect(within(heading.nextElementSibling).getByText('MSME-CC').parentElement)
      .toHaveTextContent('not reported')
  })

  it('claims no per-portfolio precision when the run published no exhibit', async () => {
    const m = metrics()
    delete m.data.metrics.rank_order.by_portfolio
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(m) }), { vi })
    render()
    expect(await screen.findByText(/published no per-portfolio rank-order exhibit/)).toBeInTheDocument()
  })

  it('ranks who to call first by rupees at risk', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const table = await screen.findByRole('table', { name: /rupees at risk/i })
    const rows = within(table).getAllByRole('rowheader')
    // MSME00001: 0.71 x 25,00,000 = 17.75 L beats HOUS00007: 0.33 x 48,00,000 = 15.84 L
    expect(rows[0]).toHaveTextContent('MSME00001')
    expect(rows[1]).toHaveTextContent('HOUS00007')
  })

  it('shows an empty state when the run published no accounts', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/portfolio`]: ok(portfolio([])) }), { vi })
    render()
    expect(await screen.findByText('No accounts in this model run')).toBeInTheDocument()
  })

  it('shows the error state when the book cannot be read', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/portfolio`]: fail(500, { code: 'internal_error', message: 'Boom.' }) }), { vi })
    render()
    expect(await screen.findByTestId('state-error')).toHaveTextContent('Could not load the book')
  })

  it('still renders the concentration panels when metrics are unavailable', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: fail(503, { code: 'upstream_error', message: 'Busy.' }) }), { vi })
    render()
    expect(await screen.findByRole('heading', { name: /by lending portfolio/ })).toBeInTheDocument()
    expect(screen.getByText(/published no per-portfolio rank-order exhibit/)).toBeInTheDocument()
  })

  it('labels every what-if slider', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByLabelText('Accounts cured by acting early')).toBeInTheDocument()
    expect(screen.getByLabelText('Provisioning rate on NPA (IRAC)')).toBeInTheDocument()
    expect(screen.getByLabelText('Assumed IDBI MSME book size')).toBeInTheDocument()
  })

  it('pages the whole book rather than showing only the first page in the exhibits', async () => {
    const api = mockApi(apiRoutes({
      [`${B}/drishti/portfolio`]: ok(portfolio(undefined, { total: 2, limit: 500, offset: 0 })),
    }), { vi })
    render()
    await screen.findByRole('heading', { name: /by lending portfolio/ })
    const call = api.calls.find((c) => c.path === `${B}/drishti/portfolio`)
    expect(call.url).toContain('limit=500')
  })

  it('shows the ecosystem lens when the run published one', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByRole('heading', { name: /Stress travels through trading networks/ })).toBeInTheDocument()
  })

  it('omits the ecosystem lens entirely when the run published none', async () => {
    const m = metrics()
    m.data.ecosystem = null
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(envelope(m.data)) }), { vi })
    render()
    await screen.findByRole('heading', { name: /by lending portfolio/ })
    expect(screen.queryByRole('heading', { name: /Stress travels through trading networks/ })).not.toBeInTheDocument()
  })
})
