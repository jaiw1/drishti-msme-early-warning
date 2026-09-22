import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import ModelMetrics, { criteriaRows, firstSentence, formatObserved, summariseBreakdown } from './ModelMetrics'
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

  // DR-06 / DR-09 / DR-11 publish `result.value: null` and put every measurement in
  // `result.breakdown[]` — the Observed column showed an em dash beside a Pass.
  it('summarises a per-cell criterion that has no top-level value', () => {
    const rows = criteriaRows({ criteria: [{
      id: 'DR-06',
      op: 'ge',
      scope: 'per_portfolio',
      result: { value: null, status: 'pass', breakdown: [
        { level: 'Agri', value: 0.8374, status: 'pass' }, { level: 'LAP', value: 0.9069, status: 'pass' },
      ] },
    }] })
    expect(rows[0].observed).toBeNull()
    expect(rows[0].observedSummary).toBe('min 0.837 across 2 portfolios')
  })

  it('leaves a criterion that publishes both a value and a breakdown exactly as it was', () => {
    const rows = criteriaRows({ criteria: [{
      id: 'DR-07',
      op: 'report',
      result: { value: 0.8724, status: 'report', breakdown: [{ level: 'x', value: 0.1, status: 'report' }] },
    }] })
    expect(rows[0].observed).toBe(0.8724)
    expect(rows[0].observedSummary).toBeNull()
  })

  it('carries the runner’s own detail text through for the population notes', () => {
    const rows = criteriaRows({ criteria: [{
      id: 'DR-01',
      result: { value: 0.8885, status: 'pass', detail: 'pooled ROC-AUC over every eligible holdout row' },
    }] })
    expect(rows[0].detail).toBe('pooled ROC-AUC over every eligible holdout row')
  })
})

describe('formatObserved', () => {
  it('renders a band as a range rather than a comma-joined array', () => {
    expect(formatObserved([0.82, 0.92])).toBe('0.820 – 0.920')
  })

  it('renders an object-valued criterion as its fields, never [object Object]', () => {
    expect(formatObserved({ precision_at_5pct: 0.3546 })).toBe('precision at 5pct 0.355')
  })

  it('leaves integers alone and trims float noise', () => {
    expect(formatObserved(5)).toBe('5')
    expect(formatObserved(0.900881234)).toBe('0.901')
  })

  it('returns null for an absent value so the caller can print its own dash', () => {
    expect(formatObserved(null)).toBeNull()
    expect(formatObserved(undefined)).toBeNull()
  })

  // D10/D11: `Number(v.toFixed(4))` stripped trailing zeros per value, so the same column
  // printed 0.8885 on one row and 0.82 on the next.
  it('prints every non-integer at the same number of decimal places', () => {
    expect(formatObserved(0.8885)).toBe('0.888')
    expect(formatObserved(0.82)).toBe('0.820')
    expect(formatObserved(0.0331)).toBe('0.033')
    expect(formatObserved([0.82, 0.92])).toBe('0.820 – 0.920')
  })

  it('keeps an integer band an integer, never "5.000"', () => {
    expect(formatObserved(5)).toBe('5')
    expect(formatObserved(0)).toBe('0')
  })

  // DR-10 passes `< 0` with -0.000068. At three places that rounds to "-0.000", which
  // reads as a tie against a required "0" — a pass printed as a failure.
  it('never rounds a non-zero value into a false zero', () => {
    expect(formatObserved(-0.000068)).toBe('-0.000068')
    expect(formatObserved(0.0006)).toBe('0.001')
  })
})

describe('summariseBreakdown', () => {
  const cells = (values, status = 'pass') => values.map((value, i) => ({ level: `L${i}`, value, status }))

  // DR-06: a floor is gated on the WORST cell, so that is the one the column shows.
  it('summarises a floor by its minimum cell', () => {
    const result = { value: null, breakdown: cells([0.8724, 0.8605, 0.8374, 0.9069, 0.85, 0.86, 0.87, 0.88]) }
    expect(summariseBreakdown(result, { op: 'ge', scope: 'per_portfolio' }))
      .toBe('min 0.837 across 8 portfolios')
  })

  // DR-09: a ceiling is gated on the worst cell too — which is the maximum.
  it('summarises a ceiling by its maximum cell', () => {
    const result = { value: null, breakdown: cells([0.0031, 0.0047, 0.0007]) }
    expect(summariseBreakdown(result, { op: 'le', scope: 'per_cut' }))
      .toBe('max 0.0047 across 3 cells')
  })

  // DR-11's cells are [green, amber, red] triples: there is no min or max to take.
  it('summarises a non-numeric criterion by its pass count', () => {
    const result = { value: null, breakdown: cells([[0.004, 0.19, 0.97], [0.005, 0.14, 0.88]]) }
    expect(summariseBreakdown(result, { op: 'monotone_increasing', scope: 'per_portfolio' }))
      .toBe('monotone in 2/2 portfolios')
  })

  it('counts only the cells that actually passed', () => {
    const result = { value: null, breakdown: [
      { value: [1], status: 'pass' }, { value: [1], status: 'fail' }, { value: [1], status: 'pass' },
    ] }
    expect(summariseBreakdown(result, { op: 'monotone_increasing', scope: 'per_portfolio' }))
      .toBe('monotone in 2/3 portfolios')
  })

  it('says nothing at all when there is no breakdown to summarise', () => {
    expect(summariseBreakdown({ value: 0.9, breakdown: [] }, { op: 'ge' })).toBeNull()
    expect(summariseBreakdown(null, { op: 'ge' })).toBeNull()
  })
})

describe('firstSentence', () => {
  it('takes the runner’s first sentence and leaves a short one whole', () => {
    expect(firstSentence('pooled ROC-AUC over every eligible holdout row (n_accounts=13500)'))
      .toBe('pooled ROC-AUC over every eligible holdout row (n_accounts=13500)')
    expect(firstSentence('First one. Second one.')).toBe('First one.')
  })

  it('elides a sentence that runs past the cap', () => {
    expect(firstSentence('x'.repeat(400))).toHaveLength(200)
    expect(firstSentence('x'.repeat(400)).endsWith('…')).toBe(true)
  })

  it('is empty for an absent detail', () => {
    expect(firstSentence(null)).toBe('')
    expect(firstSentence('')).toBe('')
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

  // The headline rose between builds because the Red cut-off moved, not because the model
  // improved. A screen that prints only the headline lets a reviewer draw the other
  // conclusion, so the split is rendered beside it — and omitted, never faked, when the
  // published run does not carry one.
  it('prints the decomposition beside the headline, so the rise cannot read as an improvement', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const cell = metrics().data.metrics.red_precision_decomposition
    expect(await screen.findByText(cell.note)).toBeInTheDocument()
    // the counterfactual band, so the sentence can be re-derived rather than trusted
    expect(screen.getByText(/At 0\.2720: 288 Red, 237 NPA\./)).toBeInTheDocument()
    expect(screen.getByText(/At the cut-off in force: 264 Red, 244 NPA\./)).toBeInTheDocument()
  })

  it('says nothing about the decomposition when the run published none', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(metrics({ decomposition: false })) }), { vi })
    render()
    expect(await screen.findByText('92.4%')).toBeInTheDocument()
    expect(screen.queryByText(/Why it is higher than the July 2026 figure/)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/0\.2720/)
  })

  it('shows the cost pair, both sides priced on the policy fold', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const pair = (await screen.findByText(/What that operating point costs/)).closest('p')
    expect(pair).toHaveTextContent('₹6.68 cr')
    expect(pair).toHaveTextContent('₹6.80 cr')
    // the denominator, printed rather than assumed — it is NOT the 443-account book above
    expect(pair).toHaveTextContent('8,933-account policy fold')
  })

  it('says nothing about cost when the run published no policy-fold pair', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(metrics({ costModel: false })) }), { vi })
    render()
    expect(await screen.findByText('92.4%')).toBeInTheDocument()
    expect(screen.queryByText(/What that operating point costs/)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/6\.68 cr/)
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

// -------------------------------------------------------------- the population disclosures
describe('Model & Metrics — two populations, one metric', () => {
  const breakdownRun = () => ok(envelope({
    published: true,
    criteria_sha: 'abc123def4567890',
    verify_result: null,
    available: true,
    note: null,
    criteria_states: {},
    accepted_failure_ids: [],
    accepted_failures: null,
    report: {
      criteria: [
        {
          id: 'DR-01',
          description: 'Grouped AUC in band',
          op: 'between',
          threshold: [0.82, 0.92],
          result: {
            value: 0.8885,
            status: 'pass',
            detail: 'pooled ROC-AUC over every eligible holdout row (n_accounts=13500)',
            breakdown: [],
          },
        },
        {
          id: 'DR-06',
          description: 'AUC per portfolio',
          op: 'ge',
          scope: 'per_portfolio',
          threshold: 0.78,
          result: {
            value: null,
            status: 'pass',
            detail: 'AUC per portfolio, grouped-holdout test set',
            breakdown: [
              { level: 'MSME-CC', value: 0.8724, status: 'pass' },
              { level: 'Agri', value: 0.8374, status: 'pass' },
            ],
          },
        },
        {
          id: 'DR-11',
          description: 'Bands monotone in every portfolio',
          op: 'monotone_increasing',
          scope: 'per_portfolio',
          threshold: null,
          result: {
            value: null,
            status: 'pass',
            detail: 'pooled: monotone',
            breakdown: [
              { level: 'MSME-CC', value: [0.004, 0.19, 0.97], status: 'pass' },
              { level: 'Agri', value: [0.005, 0.14, 0.88], status: 'pass' },
            ],
          },
        },
      ],
    },
  }))

  // B5 — a Pass beside an em dash was the table's worst row: a verdict with no number.
  it('prints the gating cell of a per-cell criterion instead of an em dash', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: breakdownRun() }), { vi })
    render()
    const table = await screen.findByRole('table', { name: /validation criteria/i })
    expect(within(table).getByRole('rowheader', { name: 'DR-06' }).closest('tr'))
      .toHaveTextContent('min 0.837 across 2 portfolios')
    expect(within(table).getByRole('rowheader', { name: 'DR-11' }).closest('tr'))
      .toHaveTextContent('monotone in 2/2 portfolios')
  })

  // B3/B4 — the runner measures the same metrics over a different population, and a reader
  // who meets the two figures cold concludes one of them is wrong.
  it('names the population difference on the runner’s own row, in the runner’s own words', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/validation`]: breakdownRun() }), { vi })
    render()
    const table = await screen.findByRole('table', { name: /validation criteria/i })
    const dr01 = within(table).getByRole('rowheader', { name: 'DR-01' }).closest('tr')
    expect(dr01).toHaveTextContent(/labelable mature subset/)
    expect(dr01).toHaveTextContent(/pooled ROC-AUC over every eligible holdout row/)
    // Not on a row whose figure nothing on the screen contradicts.
    expect(within(table).getByRole('rowheader', { name: 'DR-06' }).closest('tr'))
      .not.toHaveTextContent(/labelable mature subset/)
  })

  it('says the same thing beside the headline precision and the ROC-AUC tile', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText(/DR-02 in the validation table below reports the/))
      .toBeInTheDocument()
    expect(screen.getByText(/DR-01 and DR-26 below measure the same metric/)).toBeInTheDocument()
  })

  // C17 — `badgeForMode` falls through to NOT_COLLECTED on every live screen while the
  // first read is in flight, and the chip's own tooltip is written about a customer field.
  it('wears the run’s own source badge, and no badge at all when no run declares one', async () => {
    mockApi(apiRoutes(), { vi })
    const { unmount } = render()
    expect(await screen.findByRole('button', { name: /Fixture/ })).toBeInTheDocument()
    unmount()

    const m = metrics()
    mockApi(apiRoutes({ [`${B}/drishti/metrics`]: ok(envelope(m.data, { provenance_mode: null })) }), { vi })
    render()
    await screen.findByText('Validation')
    expect(screen.queryByText(/Not collected/i)).not.toBeInTheDocument()
  })
})
