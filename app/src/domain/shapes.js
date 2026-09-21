// Shape adapters between the platform API, the bundled snapshot, and the screens.
//
// Both sources are legitimate and neither is canonical: the API serves a published
// `model_run` (contracts/openapi.json `x-response-shapes`), the snapshot is what
// `src/export_demo.py` wrote. Where they disagree the difference is recorded here, once,
// with a comment saying which side is which — never papered over inside a component.

import { normaliseChannels } from './channels'

/** Postgres NUMERIC arrives as a string. `"1637000.00"` is a number, not a label. */
export function num(value) {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

export const BANDS = ['red', 'amber', 'green']

/** The band a decision score falls in, under the thresholds currently in force. */
export function bandFor(score, { red_thr: red, amber_thr: amber } = {}) {
  const value = num(score)
  if (value === null || red === undefined || amber === undefined) return null
  if (value >= red) return 'red'
  if (value >= amber) return 'amber'
  return 'green'
}

/**
 * The ONE score a band may be derived from: the four-month trailing mean the model's
 * Amber/Red thresholds were searched over (`meta.decision_score` in the export contract).
 *
 * The order matters and is not a convenience. `decision_score` is the field's own name.
 * `pd_smooth` is that same number under its older name, which the API still returns.
 * `pd` is LAST because in the static payload the field called `pd` already holds the
 * smoothed value — but over the API `pd` is the raw single-month probability, and banding
 * that one moved 443 of 12,760 accounts across a band at the shipped thresholds.
 */
export function decisionScore(raw) {
  return num(raw?.decision_score ?? raw?.pd_smooth ?? raw?.pd)
}

/**
 * One watch-list row, from either source.
 *
 * `bucket` is recomputed on read against the thresholds in force (BE-7 decision 1);
 * `published_bucket` is what the model run published. They differ exactly when a manager
 * has moved a threshold since the run, and the watch-list shows both when they do —
 * hiding the difference would make an audited business decision invisible.
 */
export function toRow(raw, { thresholds } = {}) {
  const pd = num(raw.pd)
  const published = raw.published_bucket ?? raw.bucket ?? null
  // When the server did not band the row for us, band it here from the DECISION
  // score — never from `pd`, which over the API is the raw single-month probability.
  const bucket = raw.bucket ?? bandFor(decisionScore(raw), thresholds) ?? published
  return {
    ...raw,
    id: raw.id || raw.account_id,
    account_id: raw.account_id,
    portfolio: raw.portfolio ?? null,
    sector: raw.sector ?? null,
    segment: raw.segment ?? null,
    constitution: raw.constitution ?? null,
    region: raw.region ?? null,
    secured: raw.secured ?? null,
    sanctioned: num(raw.sanctioned),
    outstanding: num(raw.outstanding),
    dpd: num(raw.dpd),
    npa_status: raw.npa_status ?? null,
    utilisation: num(raw.utilisation),
    pd,
    pd_smooth: num(raw.pd_smooth),
    bucket,
    published_bucket: published,
    bucket_moved: Boolean(published && bucket && published !== bucket),
    reasons: raw.reasons || [],
    first_warning_lead: raw.first_warning_lead ?? null,
    runway_months: num(raw.runway_months ?? raw.runway?.months ?? null),
    channels_present: normaliseChannels(raw.channels_present),
  }
}

/** Ticket band, derived from the sanctioned amount. The contract has no such column. */
export const TICKET_BANDS = [
  { key: 'lt10L', label: 'Under ₹10 L', test: (v) => v < 1e6 },
  { key: '10Lto50L', label: '₹10 L – ₹50 L', test: (v) => v >= 1e6 && v < 5e6 },
  { key: '50Lto2Cr', label: '₹50 L – ₹2 Cr', test: (v) => v >= 5e6 && v < 2e7 },
  { key: 'gt2Cr', label: 'Over ₹2 Cr', test: (v) => v >= 2e7 },
]

export function ticketBand(sanctioned) {
  const v = num(sanctioned)
  if (v === null) return null
  return TICKET_BANDS.find((b) => b.test(v))?.key ?? null
}

export const DPD_BANDS = [
  { key: '0', label: 'Current (0 DPD)', test: (v) => v <= 0 },
  { key: '1-30', label: '1–30 DPD', test: (v) => v > 0 && v <= 30 },
  { key: '31-60', label: '31–60 DPD (SMA-1)', test: (v) => v > 30 && v <= 60 },
  { key: '61-90', label: '61–90 DPD (SMA-2)', test: (v) => v > 60 && v <= 90 },
  { key: '90+', label: '90+ DPD (NPA)', test: (v) => v > 90 },
]

export function dpdBand(dpd) {
  const v = num(dpd)
  if (v === null) return null
  return DPD_BANDS.find((b) => b.test(v))?.key ?? null
}

/**
 * `rank_order.by_portfolio` reaches us as a list (the export, DM-3) or as an object keyed
 * by portfolio (the platform's metrics route). Both carry the same per-portfolio exhibit.
 * Normalise to a list so the screen maps over one thing.
 */
export function byPortfolioList(rankOrder) {
  const raw = rankOrder?.by_portfolio
  if (!raw) return []
  const entries = Array.isArray(raw)
    ? raw.map((entry) => ({ ...entry }))
    : Object.entries(raw).map(([portfolio, entry]) => ({ portfolio, ...entry }))
  return entries
    .filter((entry) => entry && (entry.by_band?.length || entry.by_decile?.length))
    .sort((a, b) => String(a.portfolio ?? '').localeCompare(String(b.portfolio ?? '')))
}

/**
 * The Red-band precision figure, whichever of the three spellings this payload uses.
 * Export: `metrics.red_band_precision_8m`. API: `metrics.red_band_precision`.
 * Per-portfolio: `rank_order.by_portfolio[i].red_band_precision_8m`.
 */
export function redBandPrecision(metrics) {
  const block = metrics?.red_band_precision_8m ?? metrics?.red_band_precision ?? null
  if (!block) return null
  if (typeof block === 'number') return { value: block }
  return {
    value: num(block.value),
    ci_low: num(block.ci_low ?? block.ci_lo),
    ci_high: num(block.ci_high ?? block.ci_hi),
    n: block.n_red ?? block.n ?? null,
    hits: block.n_red_npa ?? block.defaults ?? null,
    method: block.method || null,
    horizon_months: block.horizon_months ?? metrics?.rank_order?.horizon_months ?? null,
  }
}

/**
 * The honesty block, verbatim. `export_demo.py` re-derives every claim in it from the
 * measured numbers and refuses to write the file if they disagree, which is the whole
 * point: the UI must print it, never paraphrase it.
 */
export function honestyBlock(metrics) {
  const h = metrics?.honesty
  if (!h || typeof h !== 'object') return null
  if (!h.headline && !h.why) return null
  return {
    headline: h.headline || null,
    why: h.why || null,
    notClaimed: h.not_claimed || null,
    derivedFrom: Array.isArray(h.derived_from) ? h.derived_from : [],
  }
}

/**
 * How much of the Red-precision headline is the MODEL and how much is the CUT-OFF.
 *
 * `metrics.red_precision_decomposition`, emitted by `export_demo.py` and carried
 * unchanged through the platform's metrics route. Absent on any run built before it
 * existed, which is why every caller must treat `null` as "say nothing" rather than
 * "nothing moved" — a missing decomposition is not evidence that the headline rose on
 * merit, and printing a zeroed one would claim exactly that.
 */
export function precisionDecomposition(metrics) {
  const d = metrics?.red_precision_decomposition
  if (!d || typeof d !== 'object') return null
  const atOld = d.new_model_at_previous_threshold || {}
  const atNew = d.new_model_at_new_threshold || {}
  const previous = num(d.previous_model_precision)
  const rebanded = num(atOld.precision)
  const shipped = num(atNew.precision)
  if (previous === null || rebanded === null || shipped === null) return null
  return {
    previousThreshold: num(d.previous_threshold),
    previousPrecision: previous,
    previousNRed: d.previous_model_n_red ?? null,
    rebandedPrecision: rebanded,
    rebandedNRed: atOld.n_red ?? null,
    rebandedNTrue: atOld.n_true ?? null,
    shippedPrecision: shipped,
    shippedNRed: atNew.n_red ?? null,
    shippedNTrue: atNew.n_true ?? null,
    modelEffectPp: num(d.model_effect_pp),
    thresholdEffectPp: num(d.threshold_effect_pp),
    note: typeof d.note === 'string' && d.note.trim() ? d.note : null,
  }
}

/**
 * The policy fold's two expected-cost figures, in crore.
 *
 * `metrics.cost_model.policy_fold`. Both sides are priced on the SAME fold — the one the
 * thresholds were searched over, not the book the rest of the metrics block reports on —
 * so `nAccounts` travels with them and must be shown: a rupee total read against the
 * wrong denominator is the whole failure mode this field exists to close.
 */
export function policyFoldCost(metrics) {
  const fold = metrics?.cost_model?.policy_fold
  if (!fold || typeof fold !== 'object') return null
  const chosen = num(fold.expected_cost_chosen_cr)
  const july = num(fold.expected_cost_july_cr)
  if (chosen === null || july === null) return null
  return { nAccounts: num(fold.n_accounts), chosenCr: chosen, julyCr: july }
}

/** Provenance family map -> sorted [family, source] pairs, for the badge strip. */
export function familyBadges(families) {
  if (!families || typeof families !== 'object') return []
  return Object.entries(families)
    .map(([family, source]) => ({ family, source }))
    .sort((a, b) => a.family.localeCompare(b.family))
}
