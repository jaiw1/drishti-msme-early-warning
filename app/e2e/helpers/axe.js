// Shared axe-core runner for a11y.spec.js.
//
// Fails the test on any `serious` or `critical` violation; `moderate`/`minor` violations
// are printed (grouped by impact, with the axe-core help URL) but never fail the run — per
// the brief, they are reported, not enforced.
import AxeBuilder from '@axe-core/playwright'
import { expect } from '@playwright/test'

const IMPACTS = ['critical', 'serious', 'moderate', 'minor']
const BLOCKING = new Set(['critical', 'serious'])

export async function scanAndAssert(page, label) {
  // The shared loading state (src/components/states/Loading.jsx, data-testid
  // "state-loading") is how every screen says its data hasn't arrived yet — scanning while
  // it's up would just be auditing a spinner. `detached` also resolves immediately for a
  // screen that never shows one (nothing to wait for).
  await page.getByTestId('state-loading').waitFor({ state: 'detached', timeout: 20_000 }).catch(() => {})

  const results = await new AxeBuilder({ page }).analyze()

  const byImpact = Object.fromEntries(IMPACTS.map((i) => [i, []]))
  for (const violation of results.violations) {
    (byImpact[violation.impact] ??= []).push(violation)
  }

  const lines = [`axe [${label}]: ${results.violations.length} violation rule(s), ${results.passes.length} passed`]
  for (const impact of IMPACTS) {
    for (const v of byImpact[impact]) {
      lines.push(`  [${impact}] ${v.id} — ${v.help} (${v.nodes.length} node(s)) ${v.helpUrl}`)
    }
  }
  console.log(lines.join('\n'))

  const blocking = IMPACTS.filter((i) => BLOCKING.has(i)).flatMap((i) => byImpact[i])
  expect(blocking, `${label}: serious/critical axe violations — see the log above for detail`).toEqual([])

  return byImpact
}
