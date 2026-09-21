import { describe, expect, it } from 'vitest'
import { SOURCE } from '../components/SourceBadge'
import { badgeForFamilySource, badgeForMode } from './provenance'

describe('badgeForFamilySource', () => {
  it('reads a plain BANK_API family as the live badge, with no cached caveat', () => {
    expect(badgeForFamilySource('BANK_API')).toEqual({ source: SOURCE.BANK_API, sandbox: false })
  })

  it('reads a BANK_API family as the cached-reuse badge when the caller says it was reused', () => {
    const badge = badgeForFamilySource('BANK_API', { cached: true })
    expect(badge.source).toBe(SOURCE.BANK_API_CACHED)
    expect(badge.sandbox).toBe(false)
  })

  it('never treats a cached BANK_API family as NOT_COLLECTED', () => {
    const badge = badgeForFamilySource('BANK_API', { cached: true })
    expect(badge.source).not.toBe(SOURCE.NOT_COLLECTED)
  })

  it('names cached_from in the tooltip detail when the caller has it', () => {
    const badge = badgeForFamilySource('BANK_API', { cached: true, cachedFrom: 'API 402, pulled 2026-09-15' })
    expect(badge.detail).toContain('API 402, pulled 2026-09-15')
  })

  it('falls back to a generic cached explanation when cached_from is absent', () => {
    const badge = badgeForFamilySource('BANK_API', { cached: true })
    expect(badge.detail).toMatch(/last good response/)
  })

  it('ignores the cached flag for a family that was never BANK_API', () => {
    expect(badgeForFamilySource('SIMULATED', { cached: true })).toEqual({ source: SOURCE.SIMULATED, sandbox: false })
    expect(badgeForFamilySource('FIXTURE', { cached: true })).toEqual({ source: SOURCE.FIXTURE, sandbox: false })
  })

  it('keeps the existing sandbox-fixture behaviour untouched', () => {
    expect(badgeForFamilySource('BANK_API', { sandboxFixture: true })).toEqual({ source: SOURCE.BANK_API, sandbox: true })
    expect(badgeForFamilySource('BANK_API+SANDBOX_FIXTURE')).toEqual({ source: SOURCE.BANK_API, sandbox: true })
  })

  it('defaults an unrecognised or absent value to NOT_COLLECTED', () => {
    expect(badgeForFamilySource(undefined)).toEqual({ source: SOURCE.NOT_COLLECTED, sandbox: false })
    expect(badgeForFamilySource('something-else')).toEqual({ source: SOURCE.NOT_COLLECTED, sandbox: false })
  })
})

describe('badgeForMode', () => {
  it('still resolves the modes the sync/provenance screens already send', () => {
    expect(badgeForMode('bank', 'api').source).toBe(SOURCE.BANK_API)
    expect(badgeForMode('sandbox_fixture', 'api')).toEqual({ source: SOURCE.BANK_API, sandbox: true, detail: expect.any(String) })
    expect(badgeForMode('fixture', 'api').source).toBe(SOURCE.FIXTURE)
  })

  it('says nothing about a run when no mode was published', () => {
    expect(badgeForMode(undefined, 'api').source).toBe(SOURCE.NOT_COLLECTED)
  })
})
