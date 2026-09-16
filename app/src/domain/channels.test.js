import { describe, expect, it } from 'vitest'
import {
  CHANNEL_BY_FIELD, FIELD_STATE, canonicalChannel, channelSet, fieldState, normaliseChannels, renderField,
} from './channels'

const WITH_LIMIT = ['utilisation', 'cash_flow', 'repayment']
const WITHOUT_LIMIT = ['cash_flow', 'repayment', 'salary', 'ltv']

describe('normaliseChannels', () => {
  it('accepts the export’s list of strings', () => {
    const rows = normaliseChannels(WITH_LIMIT)
    expect(rows).toHaveLength(3)
    expect(rows[0]).toMatchObject({ channel: 'utilisation', label: 'Limit utilisation', present: true, family: 'exposure' })
  })

  it('accepts the API’s list of objects, and keeps its richer fields', () => {
    const rows = normaliseChannels([
      { channel: 'cashflow', label: 'Account inflows', present: true, family: 'cashflow', source: 'FIXTURE', fields: ['inflow'] },
    ])
    // The API spells it `cashflow`; the export spells it `cash_flow`. Same channel.
    expect(rows[0].channel).toBe('cash_flow')
    expect(rows[0].source).toBe('FIXTURE')
  })

  it('is empty, not broken, when nothing was published', () => {
    expect(normaliseChannels(undefined)).toEqual([])
    expect(normaliseChannels(null)).toEqual([])
  })

  it('carries an absent channel through as absent', () => {
    const set = channelSet([{ channel: 'utilisation', present: false }, { channel: 'repayment', present: true }])
    expect(set.has('utilisation')).toBe(false)
    expect(set.has('repayment')).toBe(true)
  })
})

describe('canonicalChannel', () => {
  it.each([['cashflow', 'cash_flow'], ['cash_flow', 'cash_flow'], ['UTILISATION', 'utilisation'], ['dpd', 'repayment']])(
    '%s -> %s', (input, expected) => expect(canonicalChannel(input)).toBe(expected),
  )
})

describe('fieldState — the difference between zero and nothing', () => {
  it('calls an observed number observed, including a real zero', () => {
    expect(fieldState(0.92, 'utilisation', WITH_LIMIT)).toBe(FIELD_STATE.OBSERVED)
    expect(fieldState(0, 'utilisation', WITH_LIMIT)).toBe(FIELD_STATE.OBSERVED)
  })

  it('calls a null in a portfolio WITHOUT the channel "not applicable"', () => {
    expect(fieldState(null, 'utilisation', WITHOUT_LIMIT)).toBe(FIELD_STATE.NOT_APPLICABLE)
  })

  it('calls a null in a portfolio WITH the channel "not observed"', () => {
    expect(fieldState(null, 'utilisation', WITH_LIMIT)).toBe(FIELD_STATE.UNOBSERVED)
  })

  it('claims nothing when the account published no channel list at all', () => {
    // No evidence is not evidence of absence: without a channel list we must not assert
    // "this product has no such thing".
    expect(fieldState(null, 'utilisation', [])).toBe(FIELD_STATE.UNOBSERVED)
    expect(fieldState(null, 'utilisation', undefined)).toBe(FIELD_STATE.UNOBSERVED)
  })

  it('knows which channel supplies each field the reason codes use', () => {
    expect(CHANNEL_BY_FIELD.utilisation).toBe('utilisation')
    expect(CHANNEL_BY_FIELD.sales_trend_3m).toBe('gst')
    expect(CHANNEL_BY_FIELD.salary_vs_6m_avg).toBe('salary')
    expect(CHANNEL_BY_FIELD.inflow_vs_6m_avg).toBe('cash_flow')
    expect(CHANNEL_BY_FIELD.dpd).toBe('repayment')
  })
})

describe('renderField', () => {
  const asPct = (v) => `${Math.round(v * 100)}%`

  it('renders the number when there is one', () => {
    expect(renderField(0.924, 'utilisation', WITH_LIMIT, asPct)).toMatchObject({ text: '92%', value: 0.924 })
  })

  it('renders "not applicable" — never 0% — for a portfolio with no credit limit', () => {
    // This is the bug: `null * 100` is 0, which drew a housing borrower at a flat 0%.
    const result = renderField(null, 'utilisation', WITHOUT_LIMIT, asPct)
    expect(result.text).toBe('not applicable')
    expect(result.text).not.toBe('0%')
    expect(result.value).toBeNull()
  })

  it('distinguishes "not observed" from "not applicable"', () => {
    expect(renderField(null, 'utilisation', WITH_LIMIT, asPct).text).toBe('not observed')
  })
})
