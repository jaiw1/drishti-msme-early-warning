// Observation channels, and the difference between "zero" and "there is no such thing".
//
// The eight-portfolio panel is deliberately sparse: a housing loan has no credit-limit
// utilisation and a KCC account has no salary credit. `export_demo.py` emits those fields
// as `null` and publishes `channels_present` per account so the UI can say *why* the
// number is absent. Rendering `null` as `0` draws a flat 0% line and invents a fact —
// which is exactly the failure this module exists to prevent.
//
// Two shapes reach us and both are legitimate:
//   * the export  — `channels_present: ["utilisation", "cash_flow", …]` (strings)
//   * the API     — `channels_present: [{channel, label, present, family, source, fields}]`
// `normaliseChannels` collapses them into the second, which is the richer one.

/** The fourteen channels `generator/portfolios.py` declares, plus the two the API adds. */
export const CHANNEL_SPEC = {
  repayment: {
    label: 'Repayment behaviour',
    family: 'repayment',
    fields: ['dpd', 'dpd_max_6m', 'times_late_6m', 'bounces_6m', 'minbal_breach_6m',
      'collection_ratio', 'collection_ratio_3m', 'npa_status', 'asset_classification'],
  },
  utilisation: {
    label: 'Limit utilisation',
    family: 'exposure',
    fields: ['utilisation', 'util_avg_3m', 'util_max_6m', 'months_over_90pct_util_6m'],
  },
  drawing_power: { label: 'Drawing power', family: 'exposure', fields: ['drawing_power'] },
  cash_flow: {
    label: 'Account inflows',
    family: 'cashflow',
    fields: ['inflow', 'inflow_vs_6m_avg', 'inflow_trend_3m'],
  },
  transactions: { label: 'Transaction activity', family: 'cashflow', fields: ['txn_count', 'txn_drop_flag'] },
  gst: { label: 'GST filings', family: 'filings', fields: ['gst_sales', 'sales_trend_3m'] },
  adverse: { label: 'Adverse filings', family: 'filings', fields: ['adverse_remark', 'adverse_remark_6m'] },
  salary: { label: 'Salary credits', family: 'cashflow', fields: ['salary_credit', 'salary_vs_6m_avg', 'salary_gap_6m'] },
  emi_stacking: { label: 'EMIs to other lenders', family: 'exposure', fields: ['other_bank_emi', 'emi_burden_ratio'] },
  ltv: { label: 'Loan-to-value', family: 'exposure', fields: ['ltv', 'ltv_vs_schedule'] },
  rental: { label: 'Rental income', family: 'cashflow', fields: ['rental_income', 'rental_vs_6m_avg'] },
  harvest: { label: 'Crop receipts', family: 'cashflow', fields: ['crop_receipt', 'crop_receipt_vs_norm', 'renewal_overdue_months'] },
  moratorium: { label: 'Moratorium', family: 'repayment', fields: ['moratorium_active', 'months_since_moratorium_end'] },
  commute: { label: 'Commute / fuel spend', family: 'cashflow', fields: ['commute_spend', 'commute_vs_6m_avg'] },
  // Present in the API's richer list, absent from the generator's channel tuple.
  ecosystem: { label: 'Trading-partner linkage', family: 'filings', fields: ['eco_partners', 'eco_flagged', 'eco_red'] },
  profile: { label: 'Borrower profile', family: 'profile', fields: ['vintage_months', 'business_age_years', 'sector'] },
  bureau: { label: 'Bureau', family: 'bureau', fields: ['bureau_score'] },
}

/** The API spells two channels differently from the export. Same thing. */
const ALIAS = { cashflow: 'cash_flow', cash_flow: 'cash_flow', filings: 'gst', dpd: 'repayment' }

export const canonicalChannel = (name) => {
  const key = String(name ?? '').trim().toLowerCase()
  return ALIAS[key] || key
}

/** field name -> the channel that supplies it. Derived once from CHANNEL_SPEC. */
export const CHANNEL_BY_FIELD = Object.entries(CHANNEL_SPEC).reduce((acc, [channel, spec]) => {
  for (const field of spec.fields) acc[field] = channel
  return acc
}, {})

/**
 * One list of channel rows, whichever shape came in.
 * @returns {Array<{channel,label,present,family,source,fields}>}
 */
export function normaliseChannels(value, { source = null } = {}) {
  if (!Array.isArray(value)) return []
  return value.map((entry) => {
    if (entry && typeof entry === 'object') {
      const channel = canonicalChannel(entry.channel)
      const spec = CHANNEL_SPEC[channel] || {}
      return {
        channel,
        label: entry.label || spec.label || channel,
        present: entry.present !== false,
        family: entry.family || spec.family || null,
        source: entry.source || source,
        fields: entry.fields || spec.fields || [],
      }
    }
    const channel = canonicalChannel(entry)
    const spec = CHANNEL_SPEC[channel] || {}
    return {
      channel,
      label: spec.label || channel,
      present: true,
      family: spec.family || null,
      source,
      fields: spec.fields || [],
    }
  })
}

/** The set of channel keys an account actually has. */
export function channelSet(channels) {
  return new Set(normaliseChannels(channels).filter((c) => c.present).map((c) => c.channel))
}

export const FIELD_STATE = {
  OBSERVED: 'observed',
  NOT_APPLICABLE: 'not_applicable',
  UNOBSERVED: 'unobserved',
}

/**
 * Why is this field's value what it is?
 *
 *   observed        — a real number; render it
 *   not_applicable  — this product has no such channel; render "not applicable"
 *   unobserved      — the channel exists but nothing came back; render "not observed"
 *
 * The three are different claims and a dashboard that conflates them lies about the book.
 */
export function fieldState(value, field, channels) {
  if (value !== null && value !== undefined && !(typeof value === 'number' && Number.isNaN(value))) {
    return FIELD_STATE.OBSERVED
  }
  const channel = CHANNEL_BY_FIELD[field]
  if (!channel) return FIELD_STATE.UNOBSERVED
  const present = channelSet(channels)
  // An empty channel list tells us nothing — do not claim "not applicable" on no evidence.
  if (present.size === 0) return FIELD_STATE.UNOBSERVED
  return present.has(channel) ? FIELD_STATE.UNOBSERVED : FIELD_STATE.NOT_APPLICABLE
}

export const FIELD_STATE_LABEL = {
  [FIELD_STATE.NOT_APPLICABLE]: 'not applicable',
  [FIELD_STATE.UNOBSERVED]: 'not observed',
}

/**
 * A value ready to render: either the formatted number, or the honest words.
 * @param {*} value    the raw value, possibly null
 * @param {string} field the column name, so the channel can be looked up
 * @param {*} channels  channels_present in either shape
 * @param {(v:*)=>string} format
 */
export function renderField(value, field, channels, format = (v) => String(v)) {
  const state = fieldState(value, field, channels)
  if (state === FIELD_STATE.OBSERVED) return { state, text: format(value), value }
  return { state, text: FIELD_STATE_LABEL[state], value: null }
}
