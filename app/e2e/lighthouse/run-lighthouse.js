#!/usr/bin/env node
// One-shot Lighthouse run against the preview build.
//
// Two passes, in one Chrome profile via CDP:
//   1. /drishti/login   — unauthenticated (nothing has signed in yet).
//   2. /drishti/watchlist — authenticated: after pass 1, this script signs in for real
//      (the same tolerant helper the Playwright specs use) in a page on the *same*
//      browser, so pass 2's tab inherits the session cookie from that profile — Lighthouse
//      itself never touches credentials.
//
// Not run through the Playwright test runner (plain Node), so it drives `chromium` and
// `expect` directly from `@playwright/test` rather than via `test()`.
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import lighthouse from 'lighthouse'
import { chromium } from '@playwright/test'
import { signIn } from '../helpers/auth.js'
import { USERS } from '../helpers/users.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = __dirname
const CDP_PORT = 9455
const ORIGIN = 'http://localhost:4173'
const CATEGORIES = ['performance', 'accessibility']

async function runPass(name, url) {
  const result = await lighthouse(
    url,
    { port: CDP_PORT, output: ['json', 'html'], onlyCategories: CATEGORIES, logLevel: 'error' },
    undefined,
  )
  const { lhr } = result
  const [jsonReport, htmlReport] = result.report

  await mkdir(OUT_DIR, { recursive: true })
  await writeFile(path.join(OUT_DIR, `${name}.report.json`), jsonReport)
  await writeFile(path.join(OUT_DIR, `${name}.report.html`), htmlReport)

  return {
    name,
    url,
    performance: lhr.categories.performance ? Math.round(lhr.categories.performance.score * 100) : null,
    accessibility: lhr.categories.accessibility ? Math.round(lhr.categories.accessibility.score * 100) : null,
    lhr,
  }
}

function topAudits(lhr, n = 3) {
  // Every audit that actually cost points, worst first — the standard way to read "why is
  // performance low" out of a Lighthouse result without re-deriving it by hand.
  const perf = lhr.categories.performance
  if (!perf) return []
  const byId = lhr.audits
  return perf.auditRefs
    .filter((ref) => ref.weight > 0 && byId[ref.id] && byId[ref.id].score !== null && byId[ref.id].score < 1)
    .map((ref) => ({
      id: ref.id,
      weight: ref.weight,
      score: byId[ref.id].score,
      title: byId[ref.id].title,
      displayValue: byId[ref.id].displayValue || '',
    }))
    .sort((a, b) => a.weight * a.score - b.weight * b.score) // lowest weighted contribution first
    .slice(0, n)
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: [`--remote-debugging-port=${CDP_PORT}`],
  })

  try {
    console.log('--- pass 1: /drishti/login (unauthenticated) ---')
    const loginPass = await runPass('login', `${ORIGIN}/drishti/login`)

    console.log('--- signing in (same Chrome profile, so pass 2 inherits the session cookie) ---')
    const page = await browser.newPage()
    await page.goto(`${ORIGIN}/drishti/login`)
    await signIn(page, USERS.admin.username)
    await page.close()

    console.log('--- pass 2: /drishti/watchlist (authenticated) ---')
    const watchlistPass = await runPass('watchlist', `${ORIGIN}/drishti/watchlist`)

    for (const pass of [loginPass, watchlistPass]) {
      console.log(`\n${pass.name} (${pass.url})`)
      console.log(`  performance:   ${pass.performance}`)
      console.log(`  accessibility: ${pass.accessibility}`)
      if (pass.performance !== null && pass.performance < 80) {
        console.log('  top performance causes:')
        for (const a of topAudits(pass.lhr)) {
          console.log(`    - ${a.title} [${a.id}] score=${a.score} ${a.displayValue}`)
        }
      }
    }
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
