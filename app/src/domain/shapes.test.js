import { describe, expect, it } from 'vitest'
import {
  bandFor, byPortfolioList, dpdBand, honestyBlock, num, redBandPrecision, ticketBand, toRow,
} from './shapes'
import { ROW_WITHOUT_LIMIT, ROW_WITH_LIMIT, metrics } from '../test/fixtures/api'

describe('num', () => {
  it('reads a Postgres NUMERIC string as the number it is', () => {
    expect(num('1637000.00')).toBe(1637000)
  })
  it('keeps null null rather than turning it into zero', () => {
    expect(num(null)).toBeNull()
    expect(num(undefined)).toBeNull()
    expect(num('')).toBeNull()
    expect(num('not a number')).toBeNull()
  })
})

describe('bandFor', () => {
  const t = { red_thr: 0.5, amber_thr: 0.2 }
  it.each([[0.9, 'red'], [0.5, 'red'], [0.35, 'amber'], [0.2, 'amber'], [0.05, 'green']])(
    'pd %s is %s', (pd, band) => expect(bandFor(pd, t)).toBe(band),
  )
  it('claims no band without thresholds', () => expect(bandFor(0.9, {})).toBeNull())
})

describe('toRow', () => {
  it('flags a row whose band was recomputed away from its published one', () => {
    const row = toRow(ROW_WITH_LIMIT, { thresholds: { red_thr: 0.5, amber_thr: 0.2 } })
    expect(row.bucket).toBe('red')
    expect(row.published_bucket).toBe('amber')
    expect(row.bucket_moved).toBe(true)
  })

  it('does not flag a row whose bands agree', () => {
    expect(toRow(ROW_WITHOUT_LIMIT).bucket_moved).toBe(false)
  })

  it('leaves a null utilisation null', () => {
    expect(toRow(ROW_WITHOUT_LIMIT).utilisation).toBeNull()
  })

  it('normalises the channel list so the detail screen gets one shape', () => {
    expect(toRow(ROW_WITHOUT_LIMIT).channels_present.map((c) => c.channel))
      .not.toContain('utilisation')
  })
})

describe('derived bands', () => {
  it.each([[0, '0'], [15, '1-30'], [45, '31-60'], [75, '61-90'], [200, '90+']])(
    'dpd %s is band %s', (dpd, band) => expect(dpdBand(dpd)).toBe(band),
  )
  it.each([[500000, 'lt10L'], [2500000, '10Lto50L'], [9000000, '50Lto2Cr'], [30000000, 'gt2Cr']])(
    'ticket %s is band %s', (v, band) => expect(ticketBand(v)).toBe(band),
  )
  it('claims no band for an absent figure', () => {
    expect(dpdBand(null)).toBeNull()
    expect(ticketBand(null)).toBeNull()
  })
})

describe('byPortfolioList — the API and the export disagree about the shape', () => {
  it('reads the API’s object keyed by portfolio', () => {
    const list = byPortfolioList(metrics().data.metrics.rank_order)
    expect(list.map((e) => e.portfolio)).toEqual(['Housing', 'MSME-CC'])
    expect(list[0].by_band).toHaveLength(3)
  })

  it('reads the export’s array, and produces the same thing', () => {
    const asObject = byPortfolioList(metrics().data.metrics.rank_order)
    const asArray = byPortfolioList(metrics({ byPortfolioAsArray: true }).data.metrics.rank_order)
    expect(asArray.map((e) => e.portfolio)).toEqual(asObject.map((e) => e.portfolio))
  })

  it('drops an entry with no exhibit rather than rendering an empty chart', () => {
    expect(byPortfolioList({ by_portfolio: { Auto: { n: 0 } } })).toEqual([])
  })

  it('is empty when the run published no per-portfolio exhibit', () => {
    expect(byPortfolioList(undefined)).toEqual([])
    expect(byPortfolioList({})).toEqual([])
  })
})

describe('redBandPrecision', () => {
  it('reads the export’s spelling', () => {
    const p = redBandPrecision(metrics().data.metrics)
    expect(p).toMatchObject({ value: 0.924, ci_low: 0.886, ci_high: 0.95, n: 264, hits: 244, method: 'wilson' })
  })

  it('reads the platform’s spelling and its ci_lo/ci_hi field names', () => {
    const p = redBandPrecision({ red_band_precision: { value: 1, ci_lo: 0.8, ci_hi: 1, n_red: 16, n_red_npa: 16 } })
    expect(p).toMatchObject({ value: 1, ci_low: 0.8, ci_high: 1, n: 16 })
  })

  it('claims nothing when the run published nothing', () => {
    expect(redBandPrecision({})).toBeNull()
    expect(redBandPrecision(undefined)).toBeNull()
  })
})

describe('honestyBlock', () => {
  it('carries the headline and the why through untouched', () => {
    const h = honestyBlock(metrics().data.metrics)
    expect(h.headline).toContain('92.4%')
    expect(h.why).toContain('68.7% raw accuracy')
    expect(h.notClaimed).toBe('accuracy')
  })

  it('is null when the export has no honesty block, so the screen falls back', () => {
    expect(honestyBlock(metrics({ honesty: false }).data.metrics)).toBeNull()
    expect(honestyBlock({ honesty: {} })).toBeNull()
  })
})
