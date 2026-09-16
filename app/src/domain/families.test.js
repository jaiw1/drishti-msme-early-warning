import { describe, expect, it } from 'vitest'
import { FAMILY_COUNT, SIGNAL_FAMILIES, coverageGap, familiesIn, shareTotal } from './families'
import { NINE_FAMILY_SHARES } from '../test/fixtures/api'

const NINE_ROWS = [
  { bucket: '7-9 mo', shares: { ...NINE_FAMILY_SHARES } },
  { bucket: '10-12 mo', shares: { ...NINE_FAMILY_SHARES } },
]

// What the cockpit used to hard-code, and what the four-family shortfall looked like.
const FIVE_ROWS = [{
  bucket: '10-12 mo',
  shares: {
    'Days-past-due / repayment': 2.1,
    'Cash-flow (inflows / GST)': 44.7,
    'Credit-limit utilisation': 36.2,
    'Adverse filings': 1.4,
    'Borrower profile': 15.6,
  },
}]

describe('the feature families the leakage exhibit is stacked by', () => {
  it('declares the nine that src/rigor.py GROUPS emits', () => {
    expect(FAMILY_COUNT).toBe(9)
    expect(SIGNAL_FAMILIES.map((f) => f.key)).toEqual([
      'Days-past-due / repayment',
      'Cash-flow (inflows / GST)',
      'Demand vs collection',
      'Credit-limit utilisation',
      'Income & balance',
      'Leverage & collateral',
      'Bureau',
      'Adverse filings',
      'Borrower profile',
    ])
  })

  it('gives every family its own colour', () => {
    expect(new Set(SIGNAL_FAMILIES.map((f) => f.color)).size).toBe(FAMILY_COUNT)
  })

  it('finds all nine in a nine-family export, and they sum to 100%', () => {
    const families = familiesIn(NINE_ROWS)
    expect(families).toHaveLength(9)
    for (const row of NINE_ROWS) expect(shareTotal(row)).toBeCloseTo(100, 5)
    // The regression: rendering only five of nine left a third of the attribution off the
    // chart while the axis still claimed to run to 100%.
    expect(coverageGap(NINE_ROWS, families)).toBeLessThanOrEqual(0.5)
  })

  it('reports the shortfall when the renderer is missing families', () => {
    const onlyFive = SIGNAL_FAMILIES.filter((f) => f.key in FIVE_ROWS[0].shares).slice(0, 3)
    expect(coverageGap(NINE_ROWS, onlyFive)).toBeGreaterThan(0.5)
  })

  it('still renders an older five-family export without inventing the missing four', () => {
    const families = familiesIn(FIVE_ROWS)
    expect(families).toHaveLength(5)
    expect(coverageGap(FIVE_ROWS, families)).toBeLessThanOrEqual(0.5)
  })

  it('draws a family it has never heard of rather than dropping it', () => {
    const rows = [{ bucket: 'x', shares: { ...NINE_FAMILY_SHARES, 'Something new': 3.0 } }]
    const families = familiesIn(rows)
    expect(families).toHaveLength(10)
    expect(families.at(-1)).toMatchObject({ key: 'Something new' })
    expect(families.at(-1).color).toMatch(/^#/)
  })

  it('survives an empty or absent leakage block', () => {
    expect(familiesIn([])).toEqual([])
    expect(familiesIn(undefined)).toEqual([])
    expect(coverageGap(undefined)).toBe(0)
  })
})
