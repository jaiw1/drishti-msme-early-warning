import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import DataSources, { syncState } from './DataSources'
import { renderScreen } from '../test/render'
import { B, apiRoutes, envelope, fail, mockApi, ok, provenanceEnvelope } from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = (opts) => renderScreen(<DataSources />, { path: '/data-sources', ...opts })

describe('syncState', () => {
  it('calls an uncalled endpoint never called', () => {
    expect(syncState({ calls: 0, subscription_status: null })).toBe('never')
  })
  it('calls an unapproved subscription pending, not an error', () => {
    expect(syncState({ calls: 0, subscription_status: 'pending' })).toBe('pending')
  })
  it('calls a sandbox-answered pull sandbox, not OK', () => {
    // "we called the bank's API" and "these are the bank's numbers" are different claims.
    expect(syncState({ calls: 4, last_status: '200', last_mode: 'sandbox_fixture' })).toBe('sandbox')
    expect(syncState({ calls: 4, last_status: '200', live: false })).toBe('sandbox')
  })
  it('calls a live pull OK', () => {
    expect(syncState({ calls: 4, last_status: '200', last_mode: 'live', live: true })).toBe('ok')
  })
  it('calls an error an error even when the subscription is also pending', () => {
    expect(syncState({ calls: 0, subscription_status: 'pending', error: 'timeout' })).toBe('error')
    expect(syncState({ calls: 2, last_status: '502' })).toBe('error')
  })
  it('calls a reused answer cached, not OK or sandbox', () => {
    // "the bank said this" and "the bank said this last Tuesday" are different facts.
    expect(syncState({ calls: 4, last_status: '200', served_from_cache: true })).toBe('cached')
    expect(syncState({ calls: 4, last_status: '200', last_mode: 'cached' })).toBe('cached')
  })
})

describe('Data sources & sync', () => {
  it('states plainly that no screen is showing the bank’s production numbers', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText(/No screen in this product is showing the bank’s production numbers/))
      .toBeInTheDocument()
  })

  it('shows each of the four per-API states, including the pending one', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const table = await screen.findByRole('table', { name: /bank APIs/i })
    expect(within(table).getByRole('rowheader', { name: '402' }).closest('tr'))
      .toHaveTextContent('Bank sandbox (mock, static)')
    expect(within(table).getByRole('rowheader', { name: '404' }).closest('tr'))
      .toHaveTextContent('Subscription pending')
    expect(within(table).getByRole('rowheader', { name: '362' }).closest('tr'))
      .toHaveTextContent('Never called')
  })

  it('says "bank sandbox (mock, static)" rather than borrowing a live pull’s credibility', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText('1 bank sandbox (mock, static)')).toBeInTheDocument()
  })

  it('shows the published run per product, and says so when one has none', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByRole('heading', { name: 'drishti' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'sanket' })).toBeInTheDocument()
    expect(screen.getByText('no published run')).toBeInTheDocument()
    expect(screen.getByText(/That is the honest state, not an outage/)).toBeInTheDocument()
  })

  it('badges every provenance family', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const heading = await screen.findByText('Provenance, by data family')
    const section = heading.closest('section')
    expect(within(section).getByText('cashflow')).toBeInTheDocument()
    expect(within(section).getAllByRole('button', { name: 'Simulated' }).length).toBeGreaterThan(0)
  })

  it('shows an empty state — not an empty table — when nothing has been pulled', async () => {
    mockApi(apiRoutes({ [`${B}/meta/sync`]: ok(envelope([], { total: 0, runs: {}, real_data: false })) }), { vi })
    render()
    expect(await screen.findByText('No API has been registered against a pull yet')).toBeInTheDocument()
  })

  it('shows the error state when sync cannot be read', async () => {
    mockApi(apiRoutes({ [`${B}/meta/sync`]: fail(500, { code: 'internal_error', message: 'Boom.' }) }), { vi })
    render()
    expect(await screen.findByTestId('state-error')).toHaveTextContent('Could not read the sync status')
  })

  it('claims nothing in the frozen bundle, and says why', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (String(url).endsWith('demo_data.json')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => ({ meta: { provenance: { model: 'SIMULATED' } }, portfolio_summary: {}, portfolio: [], timelines: {}, memos: {} }),
        }
      }
      throw new Error(`unexpected fetch ${url}`)
    }))
    render({ mode: 'static' })
    expect(await screen.findByText('This bundle has no backend to ask')).toBeInTheDocument()
  })
})

describe('Data sources & sync — cached last-good pulls', () => {
  const cachedSyncRow = {
    api_id: '442', label: 'CIF exposure and rating', used_by: ['drishti'], calls: 6, records: 240,
    last_status: '200', last_mode: 'cached', last_pulled_at: '2026-09-21T02:00:00Z',
    last_success_at: '2026-09-16T02:00:00Z', subscription_status: 'approved',
    endpoint: '/exposure', latency_ms: 190, error: null, note: null, live: false,
    served_from_cache: true, cached_calls: 2,
  }

  it('renders a reused endpoint as "Bank API · last good pull", dated by last_success_at', async () => {
    mockApi(apiRoutes({ [`${B}/meta/sync`]: ok(envelope([cachedSyncRow], { total: 1, runs: {}, real_data: false })) }), { vi })
    render()
    const table = await screen.findByRole('table', { name: /bank APIs/i })
    const row = within(table).getByRole('rowheader', { name: '442' }).closest('tr')
    const statusCell = row.querySelectorAll('td')[row.querySelectorAll('td').length - 1]
    expect(statusCell).toHaveTextContent('Bank API · last good pull')
    // Dated by last_success_at (16 Sep 2026), not last_pulled_at (21 Sep 2026).
    expect(statusCell.textContent).toContain(new Date(cachedSyncRow.last_success_at).toLocaleString('en-IN'))
    // Never mistaken for a live "OK" pull.
    expect(statusCell).not.toHaveTextContent(/\bOK\b/)
  })

  it('adds a disclosure-strip line when the platform reused a cached answer', async () => {
    mockApi(apiRoutes({
      [`${B}/meta/provenance`]: ok(provenanceEnvelope({
        cached: { apis: ['442', '408'], calls: 5, last_reused_at: '2026-09-21T02:00:00Z', note: 'reused' },
      })),
    }), { vi })
    render()
    const strip = (await screen.findByText(/No screen in this product is showing/)).closest('section')
    expect(strip).toHaveTextContent(/2 APIs answered tonight from a cached last-good pull/)
  })

  it('says nothing about a cached reuse when none happened', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const strip = (await screen.findByText(/No screen in this product is showing/)).closest('section')
    expect(strip).not.toHaveTextContent(/cached last-good pull/)
  })

  it('badges a family as the cached-reuse variant in the frozen bundle when cached_families names it', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (String(url).endsWith('demo_data.json')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => ({
            meta: { provenance: { cashflow: 'BANK_API', model: 'BANK_API' }, cached_families: ['cashflow', 'model'] },
            portfolio_summary: {}, portfolio: [], timelines: {}, memos: {},
          }),
        }
      }
      throw new Error(`unexpected fetch ${url}`)
    }))
    render({ mode: 'static' })
    const heading = await screen.findByText('Provenance, by data family')
    const section = heading.closest('section')
    expect(within(section).getAllByRole('button', { name: 'Bank API · last good pull' }).length).toBeGreaterThan(0)
  })
})

describe('Data sources & sync — freshness and drift', () => {
  // `GET /meta/provenance` publishes both and this screen used to drop them, so a stale run
  // or a significant population shift was visible to the platform and to nobody looking.
  it('states how old the published run is against the platform’s own staleness limit', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText('Freshness and drift')).toBeInTheDocument()
    expect(screen.getByText(/limit 36 h/)).toBeInTheDocument()
    expect(screen.getByText('fresh')).toBeInTheDocument()
  })

  it('shows the score drift with its band, not just a bare number', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText(/no material shift/)).toBeInTheDocument()
    expect(screen.getByText('0.0123')).toBeInTheDocument()
  })

  it('says why there is no drift figure rather than printing a dash', async () => {
    mockApi(apiRoutes({
      [`${B}/meta/provenance`]: ok(provenanceEnvelope({
        drift: { drishti: { available: false, reason: 'the previous run carries no scores to compare against' } },
      })),
    }), { vi })
    render()
    expect(await screen.findByText(/the previous run carries no scores to compare against/)).toBeInTheDocument()
  })

  // B7 — SANKET's sources screen leads on `live_apis`/`total`; DRISHTi never surfaced the
  // field at all, so the two products answered "how much of this is real?" differently.
  it('shows the platform’s own live-API count beside the per-row tally', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText(/APIs called live: 0 of 3/)).toBeInTheDocument()
    expect(screen.getByText('1 bank sandbox (mock, static)')).toBeInTheDocument()
  })

  it('says why the two counts can legitimately disagree', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText(/answer different questions and may legitimately disagree/))
      .toBeInTheDocument()
    expect(screen.getByText(/is cumulative/)).toBeInTheDocument()
  })

  it('counts the APIs the platform says went live, not the rows it can see', async () => {
    mockApi(apiRoutes({
      [`${B}/meta/sync`]: ok(envelope([], { total: 24, live_apis: ['402', '404'], runs: {}, real_data: true })),
    }), { vi })
    render()
    expect(await screen.findByText(/APIs called live: 2 of 24/)).toBeInTheDocument()
  })
})
