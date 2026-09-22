import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import PortfolioRiskScreen from './PortfolioRiskScreen'
import { renderScreen, session } from '../test/render'
import { B, apiRoutes, envelope, fail, metrics, mockApi, ok, portfolio } from '../test/fixtures/api'
// The real, committed export — array-shaped `by_portfolio`, `red_band_precision_8m`
// spelled `{n, hits, precision, ci_lo, ci_hi}` — as opposed to the hand-written fixture
// above, which uses the platform's `{value, ci_low, ci_high}` object-keyed spelling and
// so never exercised the export's own key names.
import demoData from '../../public/demo_data.json'

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

  it('renders per-portfolio precision from the real committed export (`precision`, not `value`)', async () => {
    const m = metrics()
    m.data.metrics.rank_order = demoData.metrics.rank_order
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(m) }), { vi })
    render()
    const heading = await screen.findByText('Red-band precision, per portfolio')
    const cards = heading.nextElementSibling
    const msmeCc = within(cards).getByText('MSME-CC').parentElement
    expect(msmeCc).not.toHaveTextContent('not reported')
    // Read the expected figures out of the export rather than pinning them here: the
    // point of this test is that the screen reads the EXPORT's key names (`precision`,
    // `ci_lo`, `hits`) and not the API's (`value`, `ci_low`), and hard-coded numbers
    // made it fail every time the model was re-run without ever testing that.
    const cell = demoData.metrics.rank_order.by_portfolio
      .find((p) => p.portfolio === 'MSME-CC').red_band_precision_8m
    const pct = (v) => `${(v * 100).toFixed(1)}%`
    expect(msmeCc).toHaveTextContent(pct(cell.precision))
    expect(msmeCc).toHaveTextContent(`95% CI ${pct(cell.ci_lo)}–${pct(cell.ci_hi)}`)
    expect(msmeCc).toHaveTextContent(`${cell.hits} of ${cell.n}`)
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

  // The what-if turns an assumed cure rate and an assumed book size into a bank-wide rupee
  // figure. That is a planning exercise for a manager. A credit officer keeps the whole of
  // the rest of the screen — including the per-portfolio Red-band precision, which is
  // exactly the number they need before they trust a Red flag.
  it('withholds the provisioning what-if from a credit officer', async () => {
    mockApi(apiRoutes(), { vi })
    render({ user: session('credit_officer') })
    await screen.findByRole('heading', { name: /by lending portfolio/ })
    expect(screen.queryByLabelText('Accounts cured by acting early')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Provisioning rate on NPA (IRAC)')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Assumed IDBI MSME book size')).not.toBeInTheDocument()
    expect(screen.queryByText(/provisioning what-if/i)).not.toBeInTheDocument()
    // and the headline card that only makes sense beside those sliders goes with them
    expect(screen.queryByText('Provisioning saved / yr')).not.toBeInTheDocument()
  })

  it('leaves the rest of the screen intact for that credit officer', async () => {
    mockApi(apiRoutes(), { vi })
    render({ user: session('credit_officer') })
    expect(await screen.findByRole('heading', { name: /by lending portfolio/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'By sector' })).toBeInTheDocument()
    expect(screen.getByText('Red-band precision, per portfolio')).toBeInTheDocument()
    expect(screen.getByText('Red exposure at risk')).toBeInTheDocument()
  })

  it.each(['manager', 'admin'])('keeps the what-if for a %s', async (role) => {
    mockApi(apiRoutes(), { vi })
    render({ user: session(role) })
    expect(await screen.findByLabelText('Accounts cured by acting early')).toBeInTheDocument()
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

  // B1 — `summary.exposure_at_risk` is the export's RED-ONLY sanctioned sum
  // (`export_demo.py`: `sanctioned where bucket == 'red'`), and the card captioned it as
  // the red+amber watch-list.
  it('captions the headline exposure as the Red population it actually is', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const card = (await screen.findByText('Red exposure at risk')).closest('div').parentElement
    expect(card).toHaveTextContent('16 Red accounts')
    expect(document.body.textContent).not.toMatch(/watch-list accounts \(red \+ amber\)/)
  })

  it('falls back to the Red rows, not to every flagged row, when the run publishes no summary', async () => {
    const m = metrics()
    delete m.data.summary.exposure_at_risk
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(m) }), { vi })
    render()
    // ROW_WITH_LIMIT is the only Red row in the fixture: ₹25,00,000 sanctioned. Summing
    // the Amber row in too was the bug the relabel exists to close.
    const card = (await screen.findByText('Red exposure at risk')).closest('div').parentElement
    expect(card).toHaveTextContent('₹25.0 L')
  })

  // B2 — `expNpa` is PD-weighted over red+amber, so it can never exceed the sanctioned sum
  // of that same population. Printed beside the Red-only figure it appeared to.
  it('compares expected NPA against the flagged book it is computed over', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const line = await screen.findByText(/expected NPA in flagged book/)
    expect(line).toHaveTextContent(/flagged \(Red \+ Amber\) exposure/)
    expect(line).toHaveTextContent(/priced on the 2 flagged accounts in this sample/)
    expect(line).toHaveTextContent(/8,933-account policy fold/)
  })

  it('drops the policy-fold clause when the run published no cost model', async () => {
    const m = metrics({ costModel: false })
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(m) }), { vi })
    render()
    const line = await screen.findByText(/expected NPA in flagged book/)
    expect(line).toHaveTextContent(/priced on the 2 flagged accounts in this sample/)
    expect(line).not.toHaveTextContent(/policy fold/)
  })

  // B16 — the sector list is a server-side `[:6]` slice of 7+ sectors and carried no
  // caption, so it read as the whole of the contagion book and did not add up to it.
  it('captions the contagion sector list as the top-N slice it is', async () => {
    const m = metrics()
    m.data.ecosystem.by_sector = [
      { sector: 'Trading', n: 129, exposure: 262428416 },
      { sector: 'Retail', n: 80, exposure: 230093362 },
    ]
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(envelope(m.data)) }), { vi })
    render()
    expect(await screen.findByRole('heading', { name: 'Top 2 sectors by exposure, within one link' }))
      .toBeInTheDocument()
  })

  it('shows no sector heading at all when the run published no sector split', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    await screen.findByRole('heading', { name: /Stress travels through trading networks/ })
    expect(screen.queryByRole('heading', { name: /sectors by exposure, within one link/ }))
      .not.toBeInTheDocument()
  })
})
