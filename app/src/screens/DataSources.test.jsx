import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import DataSources, { syncState } from './DataSources'
import { renderScreen } from '../test/render'
import { B, apiRoutes, envelope, fail, mockApi, ok } from '../test/fixtures/api'

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
