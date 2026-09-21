// Payloads shaped like the platform's, for tests that must not talk to a database.
//
// Every shape here was copied from a live `uvicorn app.main:app` answering the routes in
// `contracts/openapi.json` — including the awkward parts a hand-written fixture would
// tidy away: NUMERIC columns arrive as strings, `by_portfolio` is an object on the API and
// an array in the export, and an account in a portfolio with no credit limit carries a
// null `utilisation` and no `utilisation` channel. Those are exactly the cases the screens
// have to get right, so the fixture keeps them.

export const THRESHOLDS = { red_thr: 0.5, amber_thr: 0.2, source: 'threshold_change' }

export const envelope = (data, meta = {}) => ({
  data,
  meta: {
    request_id: 'req-test',
    model_run_id: '82569def-db67-5e0d-9e3f-4d072c630886',
    provenance_mode: 'fixture',
    generated_at: '2026-09-15T18:30:00+00:00',
    ...meta,
  },
})

const PROVENANCE = {
  model: 'FIXTURE', bureau: 'FIXTURE', filings: 'SIMULATED', profile: 'SIMULATED',
  cashflow: 'FIXTURE', exposure: 'FIXTURE', identity: 'FIXTURE', repayment: 'FIXTURE',
}

/** A credit-card account: has a limit, so utilisation is a real number. */
export const ROW_WITH_LIMIT = {
  id: 'MSME00001',
  account_id: 'MSME00001',
  cif_id: '940326772',
  portfolio: 'MSME-CC',
  constitution: 'Proprietorship',
  secured: false,
  sector: 'Trading',
  region: 'West',
  segment: 'Micro',
  sanctioned: '2500000.00',
  outstanding: '2310000.00',
  dpd: 45,
  npa_status: 'Standard',
  utilisation: 0.924,
  branch_code: '1355',
  rm_ein: 'EIN-711218',
  spotlight_rank: 1,
  provenance: PROVENANCE,
  pd: 0.71,
  pd_smooth: 0.68,
  published_bucket: 'amber',
  bucket: 'red',
  reasons: ['45 days past due', 'Credit-limit use high (92%)'],
  first_warning_lead: 9,
  runway_months: 3,
  channels_present: ['utilisation', 'cash_flow', 'gst', 'transactions', 'repayment', 'adverse'],
}

/** A housing loan: no drawable limit at all, so utilisation is null AND not a channel. */
export const ROW_WITHOUT_LIMIT = {
  id: 'HOUS00007',
  account_id: 'HOUS00007',
  cif_id: '945268836',
  portfolio: 'Housing',
  constitution: 'Individual',
  secured: true,
  sector: 'Individual',
  region: 'South',
  segment: 'Retail',
  sanctioned: '4800000.00',
  outstanding: '4410000.00',
  dpd: 0,
  npa_status: 'Standard',
  utilisation: null,
  branch_code: '1355',
  rm_ein: 'EIN-864705',
  spotlight_rank: 2,
  provenance: PROVENANCE,
  pd: 0.33,
  pd_smooth: 0.31,
  published_bucket: 'amber',
  bucket: 'amber',
  reasons: ['Salary credit 18% below the six-month average'],
  first_warning_lead: 6,
  runway_months: null,
  channels_present: ['cash_flow', 'transactions', 'repayment', 'salary', 'ltv'],
}

export const ROWS = [ROW_WITH_LIMIT, ROW_WITHOUT_LIMIT]

export const portfolio = (rows = ROWS, meta = {}) => envelope(rows, {
  total: rows.length, limit: 50, offset: 0, thresholds: THRESHOLDS, scope: 'all', ...meta,
})

// The API sends a label and a family per channel; the export sends the bare key. Tests
// need both shapes, so the object form here carries the labels the platform actually sends.
const CHANNEL_LABEL = {
  utilisation: 'Limit utilisation', cash_flow: 'Account inflows', gst: 'GST / filings',
  transactions: 'Transaction activity', repayment: 'Repayment behaviour',
  adverse: 'Adverse filings', salary: 'Salary credits', ltv: 'Loan-to-value',
}

const channelObjects = (row) => (row.channels_present || []).map((channel) => ({
  channel,
  label: CHANNEL_LABEL[channel] || channel,
  present: true,
  family: 'cashflow',
  source: 'FIXTURE',
  fields: [],
}))

export const account = (row = ROW_WITH_LIMIT) => envelope({
  ...row,
  scores: {
    pd: row.pd,
    pd_smooth: row.pd_smooth,
    pd_calibrated: null,
    bucket: row.bucket,
    published_bucket: row.published_bucket,
    reasons: row.reasons,
    first_warning_lead: row.first_warning_lead,
    runway_months: row.runway_months,
    sma2_within_6m: null,
  },
  thresholds: { red_thr: THRESHOLDS.red_thr, amber_thr: THRESHOLDS.amber_thr },
  channels_present: channelObjects(row),
  provenance_badges: { families: PROVENANCE, model: 'FIXTURE', detail: null, real_data: false },
  has_memo: true,
  actions: [],
})

export const timeline = (row = ROW_WITH_LIMIT) => envelope(
  ['2026-06', '2026-07', '2026-08', '2026-09'].map((date, i) => ({
    date,
    pd: +(row.pd - 0.09 * (3 - i)).toFixed(4),
    pd_smooth: +(row.pd_smooth - 0.09 * (3 - i)).toFixed(4),
    bucket: row.bucket,
    utilisation: row.utilisation === null ? null : +(row.utilisation - 0.02 * (3 - i)).toFixed(3),
    inflow: 200000 - 2000 * i,
    dpd: row.dpd,
  })),
  { total: 4, thresholds: THRESHOLDS, reference_month: '2026-09' },
)

export const memo = (accountId = 'MSME00001') => envelope({
  account_id: accountId,
  memo: `Early-warning memo — account ${accountId}.`,
  generated: true,
  disclaimer: 'Auto-drafted from model output and bank data. Review every figure before this text leaves the bank.',
  human_review_required: true,
})

/** Nine feature families, as `src/rigor.py` GROUPS emits them. */
export const NINE_FAMILY_SHARES = {
  'Days-past-due / repayment': 2.1,
  'Cash-flow (inflows / GST)': 36.7,
  'Demand vs collection': 10.1,
  'Credit-limit utilisation': 18.2,
  'Income & balance': 12.4,
  'Leverage & collateral': 7.3,
  Bureau: 4.6,
  'Adverse filings': 3.1,
  'Borrower profile': 5.5,
}

const bandRows = (scale = 1) => [
  { band: 'Green', n: 240, defaults: 1, bad_rate: 0.0042 * scale, ci_lo: 0.0007, ci_hi: 0.0232 },
  { band: 'Amber', n: 19, defaults: 3, bad_rate: 0.1579 * scale, ci_lo: 0.0552, ci_hi: 0.3757 },
  { band: 'Red', n: 4, defaults: 4, bad_rate: 1.0, ci_lo: 0.5101, ci_hi: 1.0 },
]

const decileRows = () => Array.from({ length: 10 }, (_, i) => ({
  decile: i + 1, pd_lo: 0.001 * (i + 1), pd_hi: 0.001 * (i + 2),
  n: 26, defaults: i > 7 ? i - 6 : 0, bad_rate: i > 7 ? (i - 6) / 26 : 0,
}))

/** The API spells `by_portfolio` as an object; the export spells it as an array. */
export const metrics = ({ byPortfolioAsArray = false, honesty = true, decomposition = true,
  costModel = true } = {}) => {
  const perPortfolio = {
    'MSME-CC': {
      n: 263, by_band: bandRows(), by_decile: decileRows(),
      red_band_precision_8m: { value: 1.0, ci_low: 0.51, ci_high: 1.0 },
      bands_monotone: true, monotone_decile_steps: 9, decile_steps: 9,
    },
    Housing: {
      n: 180, by_band: bandRows(0.5), by_decile: decileRows(),
      red_band_precision_8m: { value: 0.75, ci_low: 0.3, ci_high: 0.95 },
      bands_monotone: true, monotone_decile_steps: 8, decile_steps: 9,
    },
  }
  return envelope({
    published: true,
    metrics: {
      auc: 0.891,
      ks: 0.675,
      pr_auc: 0.677,
      base_rate: 0.3125,
      median_first_warning_months: 7,
      pct_flagged_6mo_ahead: 0.86,
      recall_at_budget: [{ budget: 0.05, recall: 0.16 }, { budget: 0.1, recall: 0.31 }],
      recall_by_lead_time: [{ bucket: '0-3 mo', recall: 0.62 }, { bucket: '4-6 mo', recall: 0.41 }],
      red_band_precision_8m: { value: 0.924, ci_low: 0.886, ci_high: 0.95, n_red: 264, n_red_npa: 244, method: 'wilson', horizon_months: 8 },
      ...(honesty ? {
        honesty: {
          headline: 'Of the accounts DRISHTi puts in the Red band, 92.4% reached NPA within eight months.',
          not_claimed: 'accuracy',
          why: 'Only 31.3% of this book reaches NPA within eight months, so a model that flagged nothing at all would score 68.7% raw accuracy. That figure tracks the base rate, not the model.',
          derived_from: ['red_band_precision_8m', 'base_rate_8m', 'raw_accuracy_8m'],
        },
      } : {}),
      // Both blocks are OPTIONAL on the wire: a run published before they existed carries
      // neither, and the screen must then say nothing rather than imply a zero.
      ...(decomposition ? {
        red_precision_decomposition: {
          previous_threshold: 0.272,
          previous_model_precision: 0.845,
          previous_model_n_red: 283,
          new_model_at_previous_threshold: { precision: 0.8229, n_red: 288, n_true: 237 },
          new_model_at_new_threshold: { precision: 0.924, n_red: 264, n_true: 244 },
          model_effect_pp: -2.2,
          threshold_effect_pp: 10.1,
          note: 'Red-band precision reads 92.4% rather than the July 2026 build’s 84.5% because Red now starts higher, not because the model improved.',
        },
      } : {}),
      ...(costModel ? {
        cost_model: {
          currency: 'INR',
          policy_fold: { n_accounts: 8933, expected_cost_chosen_cr: 6.68, expected_cost_july_cr: 6.8 },
        },
      } : {}),
      rank_order: {
        horizon_months: 8,
        definition: 'Share of snapshot accounts that reach NPA within the next 8 months.',
        n: 443,
        by_band: bandRows(),
        by_decile: decileRows(),
        bands_monotone: true,
        monotone_decile_steps: 9,
        decile_steps: 9,
        monotone_decile_step_fraction: 1.0,
        by_portfolio: byPortfolioAsArray
          ? Object.entries(perPortfolio).map(([portfolioName, entry]) => ({ portfolio: portfolioName, ...entry }))
          : perPortfolio,
      },
    },
    summary: { red: 16, amber: 144, green: 283, red_thr: 0.5, amber_thr: 0.2, total_accounts: 443, exposure_at_risk: 133204000 },
    ecosystem: { linkage: 'same sector', by_sector: [], n_amber_1link_red: 12, n_green_1link_red: 3, exposure_1link_red: 78686450 },
    rigor: {
      calibration: { ece: 0.0808, brier_raw: 0.073, brier_calibrated: 0.062, reliability: [{ pred: 0.02, obs: 0.03, n: 32 }] },
      out_of_time: { auc: 0.933, ks: 0.9, train_window: 'vintage <= 77 months', test_window: 'vintage > 77 months' },
      baseline_ladder: [{ model: 'Logistic scorecard', auc: 0.888 }, { model: 'LightGBM (ours)', auc: 0.891 }],
      leakage_by_lead: [
        { bucket: '7-9 mo', shares: { ...NINE_FAMILY_SHARES } },
        { bucket: '10-12 mo', shares: { ...NINE_FAMILY_SHARES } },
      ],
    },
    real_data: null,
    generated_from: 'data/bank/fixture.json via app.fixtures',
    provenance: PROVENANCE,
    source: 'fixture',
    n_rows: 443,
    thresholds: THRESHOLDS,
  })
}

export const validation = ({ available = true, criteriaStates = null, acceptedFailures = null } = {}) => envelope(available ? {
  published: true,
  criteria_sha: 'abc123def4567890',
  verify_result: { status: 'ok' },
  available: true,
  note: null,
  criteria_states: criteriaStates || {},
  accepted_failure_ids: acceptedFailures?.accepted || [],
  accepted_failures: acceptedFailures,
  report: {
    criteria: [
      { id: 'DR-01', description: 'Grouped AUC in band', status: 'pass', observed: 0.891, expected: '0.82–0.92' },
      { id: 'DR-05', description: 'OOT AUC ≥ 0.95× holdout', status: 'pass', observed: 1.047, expected: '≥ 0.95' },
      { id: 'DR-11', description: 'Bands monotone in every portfolio', status: 'fail', observed: '5/8', expected: '8/8' },
      { id: 'DR-15', description: 'DPD share of attribution', status: 'pending', observed: null, expected: '≤ 5%', note: 'runner 07 not run for this model run' },
    ],
  },
} : {
  published: true, report: null, criteria_sha: null, verify_result: null, available: false,
  criteria_states: {}, accepted_failure_ids: [], accepted_failures: null,
  note: 'No validation report has been loaded for this run.',
})

export const threshold = ({ history = true } = {}) => envelope({
  red_thr: 0.5,
  amber_thr: 0.2,
  source: 'threshold_change',
  changed_at: '2026-09-16T09:42:24.738069+00:00',
  change_id: 1,
  justification: 'Widened the watch tier after Q2 slippage in the trading book.',
  published_red_thr: 0.9155,
  published_amber_thr: 0.01,
  cost_model: {
    lgd: 0.65,
    currency: 'INR',
    provenance: { costs: 'SIMULATED', rates: 'FIXTURE' },
    chosen_red_thr: 0.5,
    chosen_amber_thr: 0.2,
    cost_missed_npa: 1265290,
    cost_false_positive: 4200,
    ratio_missed_to_fp: 301.3,
    officer_review_hours: 1.5,
    provision_rate: 0.15,
    expected_annual_saving: 62802500,
    curve: [
      { threshold: 0.01, n_flagged: 160, missed_npa: 0, false_positives: 110, expected_cost: 462000 },
      { threshold: 0.31, n_flagged: 46, missed_npa: 9, false_positives: 5, expected_cost: 11408610 },
      { threshold: 0.56, n_flagged: 35, missed_npa: 16, false_positives: 1, expected_cost: 20248840 },
    ],
  },
  history: history ? [{
    id: 1,
    red_thr_before: 0.9155, red_thr_after: 0.5,
    amber_thr_before: 0.01, amber_thr_after: 0.2,
    justification: 'Widened the watch tier after Q2 slippage in the trading book.',
    at: '2026-09-16T09:42:24.738069+00:00',
  }] : [],
  editable_by: ['M', 'A'],
})

export const sync = () => envelope([
  {
    api_id: '402', label: 'Overdue details', used_by: ['drishti'], calls: 12, records: 480,
    last_status: '200', last_mode: 'sandbox_fixture', last_pulled_at: '2026-09-16T09:00:00Z',
    last_success_at: '2026-09-16T09:00:00Z', subscription_status: 'approved',
    endpoint: '/overdue', latency_ms: 210, error: null, note: null, live: false,
  },
  {
    api_id: '404', label: 'Overdue position', used_by: ['drishti'], calls: 0, records: 0,
    last_status: null, last_mode: null, last_pulled_at: null, last_success_at: null,
    subscription_status: 'pending', endpoint: null, latency_ms: null, error: null,
    note: 'subscription pending', live: false,
  },
  {
    api_id: '362', label: 'Liens', used_by: ['drishti', 'sanket'], calls: 0, records: 0,
    last_status: null, last_mode: null, last_pulled_at: null, last_success_at: null,
    subscription_status: null, endpoint: null, latency_ms: null, error: null,
    note: 'never called', live: false,
  },
], {
  total: 3,
  real_data: false,
  live_apis: [],
  gateway: { mode: 'off', client_available: false, writes_allowed: false, reason: 'ATLAS_MODE=off' },
  note: 'Every row with `live: false` was answered by a fixture or never called at all.',
  runs: {
    drishti: {
      published: true, model_run_id: '82569def-db67-5e0d-9e3f-4d072c630886', schema_version: '1.0.0',
      provenance_mode: 'fixture', provenance: PROVENANCE, generated_from: 'data/bank/fixture.json',
      generated_at: '2026-09-15T18:30:00+00:00', published_at: '2026-09-16T09:41:03Z',
      n_rows: 160, source: 'fixture', run_label: 'fixture',
    },
    sanket: { published: false },
  },
})

export const provenanceEnvelope = (overrides = {}) => envelope({
  real_data: false,
  live_apis: [],
  live_records: 0,
  products: { drishti: { model_run_id: 'x', provenance_mode: 'fixture', families: PROVENANCE, status: 'published' } },
  // Calls this platform served from an earlier night's answer because tonight's call
  // failed (app/atlas/lastgood.py). Empty by default — most fixtures show a clean run —
  // so a test that wants the disclosure line overrides just this block.
  cached: { apis: [], calls: 0, last_reused_at: null, note: null },
  freshness: {
    drishti: {
      model_run_id: 'x', published_at: '2026-09-21T17:45:05Z', generated_at: '2026-09-21T15:49:29Z',
      age_hours: 1.7, stale: false, reason: null, threshold_hours: 36, n_rows: 12760,
    },
  },
  drift: {
    drishti: {
      available: true, psi: 0.0123, band: 'no_material_shift', score_field: 'pd_calibrated',
      previous_model_run_id: 'abcdef12-0000-0000-0000-000000000000',
    },
  },
  note: 'Every family reported FIXTURE has not been pulled from a bank API.',
  ...overrides,
})

export const users = () => envelope([
  {
    id: '7ef6fa0f-b64c-4f3f-80ca-01dd662549c5', username: 'a.deshmukh', full_name: 'Anita Deshmukh',
    role: 'admin', ein: 'EIN-100114', scope: [], must_change_password: false, is_active: true,
    failed_attempts: 0, locked_until: null,
  },
  {
    id: '98da0daa-fab5-4617-b151-7fa3a2becf6b', username: 's.kulkarni', full_name: 'Sneha Kulkarni',
    role: 'credit_officer', ein: 'EIN-100358', scope: ['MSME-CC', 'MSME-TL', 'LAP'],
    must_change_password: true, is_active: true, failed_attempts: 0, locked_until: null,
  },
], { total: 2 })

export const audit = () => envelope([
  {
    id: 10, ts: '2026-09-16T09:41:39Z', actor_user_id: '7ef6fa0f-b64c-4f3f-80ca-01dd662549c5',
    actor_role: 'admin', action: 'request.get.admin.users', target_type: null, target_id: null,
    request_id: 'r1', payload: { route: '/api/v1/admin/users', status: 200 },
    prev_hash: 'aa', hash: 'bb',
  },
], { total: 1, limit: 50, offset: 0 })

export const auditVerify = ({ ok = true } = {}) => envelope(
  ok
    ? { ok: true, checked: 11, first_bad_id: null, reason: null }
    : { ok: false, checked: 11, first_bad_id: 7, reason: 'hash mismatch' },
)

export const B = '/api/v1'

const jsonResponse = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: (n) => (String(n).toLowerCase() === 'content-type' ? 'application/json' : null) },
  json: async () => body,
  text: async () => JSON.stringify(body),
})

export const ok = (body) => jsonResponse(200, body)
export const fail = (status, error) => jsonResponse(status, { error: { request_id: 'req-test', ...error } })

/** The default route table: exact paths, plus `/drishti/portfolio` matched on its prefix. */
export function apiRoutes(overrides = {}) {
  return {
    [`${B}/meta/health`]: ok(envelope({ status: 'ok', database: 'ok' })),
    [`${B}/auth/me`]: ok(envelope({ username: 'demo', role: 'manager', scope: [], must_change_password: false })),
    [`${B}/drishti/portfolio`]: ok(portfolio()),
    [`${B}/drishti/metrics`]: ok(metrics()),
    [`${B}/drishti/validation`]: ok(validation()),
    [`${B}/drishti/threshold`]: ok(threshold()),
    [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}`]: ok(account(ROW_WITH_LIMIT)),
    [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}/timeline`]: ok(timeline(ROW_WITH_LIMIT)),
    [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}/memo`]: ok(memo(ROW_WITH_LIMIT.account_id)),
    [`${B}/drishti/account/${ROW_WITHOUT_LIMIT.account_id}`]: ok(account(ROW_WITHOUT_LIMIT)),
    [`${B}/drishti/account/${ROW_WITHOUT_LIMIT.account_id}/timeline`]: ok(timeline(ROW_WITHOUT_LIMIT)),
    [`${B}/drishti/account/${ROW_WITHOUT_LIMIT.account_id}/memo`]: ok(memo(ROW_WITHOUT_LIMIT.account_id)),
    [`${B}/meta/sync`]: ok(sync()),
    [`${B}/meta/provenance`]: ok(provenanceEnvelope()),
    [`${B}/admin/users`]: ok(users()),
    [`${B}/admin/audit`]: ok(audit()),
    [`POST ${B}/admin/audit/verify`]: ok(auditVerify()),
    ...overrides,
  }
}

/**
 * Stub `fetch` against a route table, matching `METHOD /path` first, then `/path`, then
 * `/path` with the query string stripped — so a test never has to guess the exact query a
 * screen will build. Returns the mock plus `calls`, for asserting what was sent.
 */
export function mockApi(routes = apiRoutes(), { vi }) {
  const calls = []
  const fetchMock = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url).split('?')[0]
    calls.push({ method, url: String(url), path, body: init.body ? JSON.parse(init.body) : null, headers: init.headers })
    const handler = routes[`${method} ${url}`] ?? routes[`${method} ${path}`] ?? routes[String(url)] ?? routes[path]
    if (!handler) throw new Error(`no mock route for ${method} ${url}`)
    return typeof handler === 'function' ? handler(url, init) : handler
  })
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.calls = calls
  return fetchMock
}
