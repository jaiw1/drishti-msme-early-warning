// Sign-in helpers shared by every spec.
//
// Every demo user comes out of global-setup.js on must_change_password + the seed
// password (see helpers/users.js). `signIn` below drives the real UI for both legs — the
// credential form, then the forced-change form — so it is exercising exactly the flow a
// human would, not calling the API directly or stubbing anything.
//
// This dev box has been observed under very heavy, bursty load from other lanes' own
// browser/test processes (see the suite's final report). The backend's login check is
// argon2id at t=3/m=64MiB — deliberately memory-hard — and under that contention it has
// taken long enough to trip the app's own 20s request timeout, which renders on /login as
// an ordinary-looking error. Treating any error there as "wrong password" would misfire on
// that timeout, so every submit below inspects *what* the error says and only falls back
// to the other password (or gives up) on a genuine credentials rejection.
import { expect } from '@playwright/test'
import { FINAL_PASSWORD, SEED_INITIAL_PASSWORD } from './users.js'

const CREDENTIALS_ERROR = /sign-in failed/i
const SLOW_TIMEOUT = 30_000

// No leading slash: baseURL carries the /drishti/ prefix, and a *relative* path joins
// onto it (a leading-slash path would instead resolve against the bare origin — that's
// what API calls in e2e specs use `/api/...` for).
//
// src/lib/mode.js gives the backend health check only 4s before the app falls back to the
// bundled "static demo" snapshot (data-testid "static-demo-banner") — a fallback that
// exists for a genuinely offline backend, but which this box's load has been observed
// tripping even though the backend answers `curl` in well under that. Reloading is exactly
// what a real user would do on a page that came up in a degraded state, so retry a few
// times rather than either faking a session or failing the whole suite on host contention.
export async function gotoLogin(page) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.goto('login')
    const isStatic = await page
      .getByTestId('static-demo-banner')
      .isVisible({ timeout: 5_000 })
      .catch(() => false)
    if (!isStatic) return
    await page.waitForTimeout(1_500)
  }
}

export async function fillLogin(page, username, password) {
  await page.locator('#login-username').fill(username)
  await page.locator('#login-password').fill(password)
  await page.getByRole('button', { name: /^sign in$/i }).click()
}

export async function fillForcedChange(page, { current, next }) {
  await page.locator('#cp-current').fill(current)
  await page.locator('#cp-new').fill(next)
  await page.locator('#cp-confirm').fill(next)
  await page.getByRole('button', { name: /change password/i }).click()
}

async function waitForOutcome(page, errorTestId, { timeout }) {
  await expect(async () => {
    const stillHere = /\/(login|change-password)(?:$|[?#])/.test(page.url())
    const errorVisible = await page.getByTestId(errorTestId).isVisible().catch(() => false)
    expect(!stillHere || errorVisible).toBe(true)
  }).toPass({ timeout })
}

/**
 * Submit the login form already on screen, retrying in place on a transient error rather
 * than assuming the password is wrong.
 * @returns {Promise<'authenticated'|'rejected'>}
 */
async function attemptLogin(page, username, password, { retries = 2 } = {}) {
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    await fillLogin(page, username, password)
    await waitForOutcome(page, 'login-error', { timeout: SLOW_TIMEOUT })
    if (!/\/login(?:$|[?#])/.test(page.url())) return 'authenticated'
    const text = await page.getByTestId('login-error').innerText().catch(() => '')
    if (CREDENTIALS_ERROR.test(text)) return 'rejected'
    if (attempt < retries) await page.waitForTimeout(1000) // network/timeout/lock copy — retry
  }
  return 'rejected'
}

/** Same idea for the forced-change form: retry a transient failure, don't misread it. */
async function attemptForcedChange(page, { current, next }, { retries = 2 } = {}) {
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    if (attempt === 0) await fillForcedChange(page, { current, next })
    else await page.getByRole('button', { name: /change password/i }).click() // fields still populated
    await waitForOutcome(page, 'change-password-error', { timeout: SLOW_TIMEOUT })
    if (!/\/change-password/.test(page.url())) return 'changed'
    if (attempt < retries) await page.waitForTimeout(1000)
  }
  return 'failed'
}

/**
 * Sign in as `username`, tolerant of whichever password the account currently holds.
 *
 * global-setup.js resets every seed user to must_change_password + SEED_INITIAL_PASSWORD
 * once, before the whole suite runs — but specs execute sequentially against that same
 * reset (workers: 1), so the *second* spec to sign in as a given user finds it already on
 * `finalPassword` from the first. This dev Postgres container is also shared with other
 * lanes, whose own seed resets have been observed landing between one API call and the
 * next during this suite's development — so a user can occasionally come back to
 * must_change_password mid-run too. Handling both password states here means a spec never
 * has to know or assume which one currently applies.
 *
 * @returns {Promise<'forced-change'|'direct'>} which path was actually taken, so a spec
 *   that wants to assert the forced-change screen was exercised can check.
 */
export async function signIn(page, username, finalPassword = FINAL_PASSWORD) {
  await gotoLogin(page)

  const seedOutcome = await attemptLogin(page, username, SEED_INITIAL_PASSWORD)
  if (seedOutcome === 'authenticated') {
    if (/\/change-password/.test(page.url())) {
      const changed = await attemptForcedChange(page, { current: SEED_INITIAL_PASSWORD, next: finalPassword })
      if (changed !== 'changed') {
        throw new Error(`signIn(${username}): forced password change did not complete.`)
      }
      return 'forced-change'
    }
    return 'direct' // seed password worked with no pending change (unusual, but tolerate it)
  }

  // Seed password genuinely rejected on credentials: this account must already be on
  // finalPassword from an earlier spec in this run.
  const finalOutcome = await attemptLogin(page, username, finalPassword)
  if (finalOutcome !== 'authenticated') {
    throw new Error(`signIn(${username}): neither the seed password nor finalPassword was accepted.`)
  }
  return 'direct'
}

export async function signOut(page) {
  await page.getByRole('button', { name: /sign out/i }).click()
  await expect(page).toHaveURL(/\/login(?:$|[?#])/, { timeout: SLOW_TIMEOUT })
}
