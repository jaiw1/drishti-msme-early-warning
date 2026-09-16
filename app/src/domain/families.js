// The feature families the leakage exhibit is stacked by.
//
// `src/rigor.py` GROUPS declares **nine**. The cockpit used to hard-code five, so the four
// added for the eight-portfolio book (Income & balance, Leverage & collateral, Bureau, and
// Demand vs collection) were dropped silently and the stacked bars no longer summed to
// 100% — a chart that says "this is everything the model looks at" while omitting a third
// of it. The list below is the nine, in the order `rigor.py` declares them; anything the
// data carries that is not in the list is still rendered, in grey, rather than dropped.
//
// "Demand vs collection" is its own family on purpose (DM-3's ruling): folding it into
// days-past-due takes the measured DPD share from ~2% to ~13%, and the model card reports
// both readings rather than inheriting one silently.

export const SIGNAL_FAMILIES = [
  { key: 'Days-past-due / repayment', color: '#dc2626' },
  { key: 'Cash-flow (inflows / GST)', color: '#0ea5e9' },
  { key: 'Demand vs collection', color: '#0891b2' },
  { key: 'Credit-limit utilisation', color: '#FF4D01' },
  { key: 'Income & balance', color: '#7c3aed' },
  { key: 'Leverage & collateral', color: '#b45309' },
  { key: 'Bureau', color: '#0f766e' },
  { key: 'Adverse filings', color: '#a855f7' },
  { key: 'Borrower profile', color: '#64748b' },
]

export const FAMILY_COUNT = SIGNAL_FAMILIES.length

const FALLBACK_COLORS = ['#475569', '#334155', '#1e293b', '#0f172a']

/**
 * The families actually present in this payload, in the canonical order, with anything
 * unexpected appended rather than discarded.
 *
 * @param {Array<{bucket:string, shares:object}>} rows `rigor.leakage_by_lead`
 */
export function familiesIn(rows) {
  const seen = new Set()
  for (const row of rows || []) {
    for (const key of Object.keys(row?.shares || {})) seen.add(key)
  }
  const known = SIGNAL_FAMILIES.filter((f) => seen.has(f.key))
  const extra = [...seen]
    .filter((key) => !SIGNAL_FAMILIES.some((f) => f.key === key))
    .sort()
    .map((key, i) => ({ key, color: FALLBACK_COLORS[i % FALLBACK_COLORS.length] }))
  return [...known, ...extra]
}

/** Total of one bucket's shares. Should be ~100; a shortfall means a dropped family. */
export function shareTotal(row) {
  return Object.values(row?.shares || {}).reduce((sum, v) => sum + (Number(v) || 0), 0)
}

/**
 * The largest gap between a bucket's rendered total and 100%, in percentage points.
 * Anything above ~0.5 pp means the chart is not showing everything the model looks at,
 * which is the bug this module exists to make impossible.
 */
export function coverageGap(rows, families = familiesIn(rows)) {
  const keys = families.map((f) => f.key)
  let worst = 0
  for (const row of rows || []) {
    const rendered = keys.reduce((sum, key) => sum + (Number(row?.shares?.[key]) || 0), 0)
    worst = Math.max(worst, Math.abs(100 - rendered))
  }
  return worst
}
