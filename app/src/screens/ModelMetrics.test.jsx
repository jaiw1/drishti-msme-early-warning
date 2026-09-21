import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import ModelMetrics, { criteriaRows, formatObserved } from './ModelMetrics'
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

  it('with no states argument, behaves exactly as before — the regression guard for old runs', () => {
    const report = { criteria: [{ id: 'DR-01', status: 'pass' }, { id: 'DR-11', status: 'fail' }, { id: 'DR-12', status: 'fail' }] }
    expect(criteriaRows(report).map((r) => r.status)).toEqual(['pass', 'fail', 'fail'])
  })

  it('with a states map, turns accepted_failure into accepted and blocking_failure into fail', () => {
    const report = { criteria: [{ id: 'DR-01', status: 'pass' }, { id: 'DR-11', status: 'fail' }, { id: 'DR-12', status: 'fail' }] }
    const rows = criteriaRows(report, { 'DR-01': 'pass', 'DR-11': 'blocking_failure', 'DR-12': 'accepted_failure' })
    expect(rows.map((r) => r.status)).toEqual(['pass', 'fail', 'accepted'])
  })

  it('falls through to statusOf for any state that is not one of the three known values', () => {
    const report = { criteria: [{ id: 'DR-01', status: 'pass' }] }
    expect(criteriaRows(report, { 'DR-01': 'warn' })[0].status).toBe('pass')
  })

  // The harness nests the measurement under `result.value`; reading only the flat keys put
  // an em dash in the Observed column of every row the platform actually serves.
  it('reads the observed value the harness nests under result.value', () => {
    const rows = criteriaRows({ criteria: [{ id: 'DR-01', result: { value: 0.8885, status: 'pass' } }] })
    expect(rows[0].observed).toBe(0.8885)
  })

  it('prefers a flat observed/value over the nested one, so older reports are unchanged', () => {
    const rows = criteriaRows({ criteria: [{ id: 'DR-01', observed: 0.5, result: { value: 0.9 } }] })
    expect(rows[0].observed).toBe(0.5)
  })

  it('calls a reported-not-gated criterion "report", never "skipped"', () => {
    const rows = criteriaRows({ criteria: [{ id: 'DR-02', result: { status: 'report', value: 0.88 } }] })
    expect(rows[0].status).toBe('report')
  })
})

describe('formatObserved', () => {
  it('renders a band as a range rather than a comma-joined array', () => {
    expect(formatObserved([0.82, 0.92])).toBe('0.82 – 0.92')
  })

  it('renders an object-valued criterion as its fields, never [object Object]', () => {
    expect(formatObserved({ precision_at_5pct: 0.3546 })).toBe('precision at 5pct 0.3546')
  })

  it('leaves integers alone and trims float noise', () => {
    expect(formatObserved(5)).toBe('5')
    expect(formatObserved(0.900881234)).toBe('0.9009')
  })

  it('returns null for an absent value so the caller can print its own dash', () => {
    expect(formatObserved(null)).toBeNull()
    expect(formatObserved(undefined)).toBeNull()
  })
})

describe('Model & Metrics', () => {
  // The platform records ONE accepted-failure list for both products, so DRISHTi's banner
  // was counting SANKET's ids too: "6 criterions" beside a tally that said 4.
  it('counts only the accepted failures this report actually carries', async () => {
    mockApi({
      ...apiRoutes(),
      [`${B}/drishti/validation`]: ok(validation({
        criteriaStates: { 'DR-11': 'accepted_failure' },
        acceptedFailures: {
          accepted: ['DR-11', 'SK-04', 'SK-23'],
          criteria: [{ id: 'DR-11', reason: 'INTERPRETATION — split into two criteria.' }],
          recorded_at: '2026-09-21T16:56:55Z',
        },
      })),
    }, { vi })
    render()
    const banner = await screen.findByText(/failed and was accepted in advance/)
    expect(banner).toHaveTextContent('1 criterion failed and was accepted in advance')
    expect(banner).toHaveTextContent('DR-11')
    expect(banner).not.toHaveTextContent('SK-04')
  })

  it('never writes "criterions"', async () => {
    mockApi({
      ...apiRoutes(),
      [`${B}/drishti/validation`]: ok(validation({
        criteriaStates: { 'DR-11': 'accepted_failure', 'DR-15': 'accepted_failure' },
        acceptedFailures: { accepted: ['DR-11', 'DR-15'], criteria: [], recorded_at: '2026-09-21T16:56:55Z' },
      })),
    }, { vi })
    render()
    expect(await screen.findByText(/2 criteria failed and were accepted in advance/)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/criterions/)
  })

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

describe('an accepted validation failure', () => {
  const REASON = 'Bureau history is too sparse at this segment size to move the metric further.'

  const acceptedFailures = {
    accepted: ['DR-12'],
    criteria: [{
      id: 'DR-12',
      metric: 'feature_stability',
      severity: 'medium',
      status: 'fail',
      value: 0.41,
      threshold: 0.6,
      op: '>=',
      n: 812,
      detail: 'Feature interaction stability check.',
      reason: REASON,
    }],
    still_blocking: ['DR-11'],
    listed_but_passing: [],
    listed_not_in_report: [],
    recorded_at: '2026-09-16T10:00:00+00:00',
    source: 'operator',
    note: 'These criteria failed and were accepted in advance, before this run published. Nothing was re-graded.',
  }

  const acceptedRun = () => ok(envelope({
    published: true,
    criteria_sha: 'abc123def4567890',
    verify_result: { status: 'ok' },
    available: true,
    note: null,
    criteria_states: { 'DR-01': 'pass', 'DR-11': 'blocking_failure', 'DR-12': 'accepted_failure' },
    accepted_failure_ids: ['DR-12'],
    accepted_failures: acceptedFailures,
    report: {
      criteria: [
        { id: 'DR-01', description: 'Grouped AUC in band', status: 'pass', observed: 0.891, expected: '0.82–0.92' },
        { id: 'DR-11', description: 'Bands monotone in every portfolio', status: 'fail', observed: '5/8', expected: '8/8' },
        { id: 'DR-12', description: 'Feature interaction stability', status: 'fail', observed: 0.41, expected: '≥ 0.6' },
      ],
    },
  }))

  it('renders it as a failure, never a pass, and keeps it out of the pass count', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: acceptedRun() }), { vi })
    render()
    const table = await screen.findByRole('table', { name: /validation criteria/i })
    const row = within(table).getByRole('rowheader', { name: 'DR-12' }).closest('tr')
    expect(row).toHaveTextContent('Fail')
    expect(row).toHaveTextContent('accepted')
    expect(row).not.toHaveTextContent('Pass')
    // Only DR-01 is a clean pass — DR-12 must not have been folded into this count.
    expect(screen.getByText('1 pass')).toBeInTheDocument()
    expect(screen.getByText('1 fail — accepted')).toBeInTheDocument()
  })

  it('renders visually distinct from a blocking failure that is still unaccepted', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: acceptedRun() }), { vi })
    render()
    const table = await screen.findByRole('table', { name: /validation criteria/i })
    const acceptedRow = within(table).getByRole('rowheader', { name: 'DR-12' }).closest('tr')
    const blockingRow = within(table).getByRole('rowheader', { name: 'DR-11' }).closest('tr')
    expect(blockingRow).toHaveTextContent('Fail')
    expect(blockingRow).not.toHaveTextContent('accepted')
    // Different row tint and a different icon/label mark the two apart at a glance.
    expect(acceptedRow.className).not.toBe(blockingRow.className)
  })

  it("shows the criterion's own pre-registered reason for the acceptance", async () => {
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: acceptedRun() }), { vi })
    render()
    expect(await screen.findByText(new RegExp(REASON))).toBeInTheDocument()
  })

  it('names the recorded acceptance near the table, without claiming anything was re-graded', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: acceptedRun() }), { vi })
    render()
    // The panel's own factual line (singular "was", since only one criterion is accepted here).
    expect(await screen.findByText(/1 criterion failed and was accepted in advance/i)).toBeInTheDocument()
    expect(screen.getByText(/2026-09-16T10:00:00\+00:00/)).toBeInTheDocument()
    // Plus the API's own explanatory note, verbatim — never a claim this code invented.
    expect(screen.getByText(acceptedFailures.note)).toBeInTheDocument()
  })

  it('renders exactly as before when a run carries none of the acceptance fields at all', async () => {
    const legacy = envelope({
      published: true,
      criteria_sha: 'abc123def4567890',
      verify_result: { status: 'ok' },
      available: true,
      note: null,
      report: {
        criteria: [
          { id: 'DR-01', description: 'Grouped AUC in band', status: 'pass', observed: 0.891, expected: '0.82–0.92' },
          { id: 'DR-11', description: 'Bands monotone in every portfolio', status: 'fail', observed: '5/8', expected: '8/8' },
        ],
      },
    })
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: ok(legacy) }), { vi })
    render()
    const table = await screen.findByRole('table', { name: /validation criteria/i })
    expect(within(table).getByRole('rowheader', { name: 'DR-01' }).closest('tr')).toHaveTextContent('Pass')
    expect(within(table).getByRole('rowheader', { name: 'DR-11' }).closest('tr')).toHaveTextContent('Fail')
    expect(screen.getByText('1 pass')).toBeInTheDocument()
    expect(screen.getByText('1 fail')).toBeInTheDocument()
    expect(screen.queryByText(/accepted in advance/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/fail — accepted/i)).not.toBeInTheDocument()
  })
})
