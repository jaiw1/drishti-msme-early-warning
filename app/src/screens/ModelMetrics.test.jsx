import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import ModelMetrics, { criteriaRows } from './ModelMetrics'
import { renderScreen } from '../test/render'
import { B, apiRoutes, envelope, fail, metrics, mockApi, ok, validation } from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = (opts) => renderScreen(<ModelMetrics />, { path: '/model', ...opts })

describe('criteriaRows', () => {
  it('reads a list of criteria objects', () => {
    const rows = criteriaRows({ criteria: [{ id: 'DR-01', status: 'pass', observed: 0.9 }] })
    expect(rows[0]).toMatchObject({ id: 'DR-01', status: 'pass', observed: 0.9 })
  })

  it('reads a map keyed by criterion id', () => {
    expect(criteriaRows({ results: { 'DR-05': { status: 'fail', observed: 0.8 } } })[0])
      .toMatchObject({ id: 'DR-05', status: 'fail' })
  })

  it('calls an unrun criterion pending, never a pass', () => {
    const rows = criteriaRows({ criteria: [{ id: 'A' }, { id: 'B', status: 'not_run' }, { id: 'C', status: null }] })
    expect(rows.map((r) => r.status)).toEqual(['pending', 'pending', 'pending'])
  })

  it('accepts the several spellings a report may use for pass and fail', () => {
    const rows = criteriaRows({ criteria: [{ id: 'A', status: 'passed' }, { id: 'B', result: 'failed' }, { id: 'C', passed: true }] })
    expect(rows.map((r) => r.status)).toEqual(['pass', 'fail', 'pass'])
  })
})

describe('Model & Metrics', () => {
  it('prints the export’s honesty block verbatim, rather than paraphrasing it', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const block = metrics().data.metrics.honesty
    expect(await screen.findByText(block.headline)).toBeInTheDocument()
    expect(screen.getByText(block.why)).toBeInTheDocument()
  })

  it('shows the Red-band precision with its confidence interval', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText('92.4%')).toBeInTheDocument()
    expect(screen.getByText(/95% wilson interval 88\.6% – 95\.0%/)).toBeInTheDocument()
    expect(screen.getByText(/244 of 264/)).toBeInTheDocument()
  })

  it('falls back to plain prose when the run published no honesty block', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(metrics({ honesty: false })) }), { vi })
    render()
    expect(await screen.findByText(/raw accuracy is meaningless here/)).toBeInTheDocument()
  })

  it('draws all nine feature families and says the bars add up', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const note = await screen.findByTestId('family-coverage')
    expect(note).toHaveTextContent('All 9 families are drawn')
    expect(note).not.toHaveTextContent('⚠')
  })

  it('renders a per-portfolio rank-order exhibit for every portfolio in the run', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByRole('heading', { name: 'Does it rank-order inside every portfolio?' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'MSME-CC' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Housing' })).toBeInTheDocument()
  })

  it('reads by_portfolio in the export’s array shape too', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(metrics({ byPortfolioAsArray: true })) }), { vi })
    render()
    expect(await screen.findByRole('heading', { name: 'MSME-CC' })).toBeInTheDocument()
  })

  it('shows every validation criterion, with pending shown as pending', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const table = (await screen.findByRole('table', { name: /validation criteria/i }))
    expect(within(table).getByRole('rowheader', { name: 'DR-01' })).toBeInTheDocument()
    const pendingRow = within(table).getByRole('rowheader', { name: 'DR-15' }).closest('tr')
    expect(pendingRow).toHaveTextContent('Pending')
    expect(pendingRow).not.toHaveTextContent('Pass')
    const failRow = within(table).getByRole('rowheader', { name: 'DR-11' }).closest('tr')
    expect(failRow).toHaveTextContent('Fail')
  })

  it('counts the outcomes honestly in the summary strip', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText('2 pass')).toBeInTheDocument()
    expect(screen.getByText('1 fail')).toBeInTheDocument()
    expect(screen.getByText('1 pending')).toBeInTheDocument()
  })

  it('says plainly when no validation report is attached to the run', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: ok(validation({ available: false })) }), { vi })
    render()
    expect(await screen.findByText('No validation report is attached to this run')).toBeInTheDocument()
  })

  it('shows the error state when the metrics call fails', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: fail(503, { code: 'upstream_error', message: 'Busy.' }) }), { vi })
    render()
    expect(await screen.findByTestId('state-error')).toHaveTextContent('Could not load the metrics')
  })

  it('shows an empty state when nothing is published, rather than blank charts', async () => {
    mockApi(apiRoutes({
      [`${B}/drishti/metrics`]: ok(envelope({ published: false, metrics: {}, summary: null, rigor: null })),
    }), { vi })
    render()
    expect(await screen.findByText('No model run is published')).toBeInTheDocument()
  })
})
