// Spec 4 — session expiry mid-use.
//
// The honest way to simulate a session ending without faking anything in app code: sign
// in for real, then remove the (HttpOnly) `rrsq_session` cookie from the browser context —
// leaving the JS-readable `rrsq_csrf` cookie in place, exactly as it would be if the
// session simply expired server-side — and trigger a real navigation that has to fetch.
// src/lib/api.js then gets a real 401 from the real backend and src/auth/AuthContext.jsx
// reacts to it exactly as it would in production.
import { test, expect } from '@playwright/test'
import { signIn } from './helpers/auth.js'
import { USERS } from './helpers/users.js'

test('an ended session redirects to /login with a return-to', async ({ page, context }) => {
  await signIn(page, USERS.creditOfficer.username)
  await expect(page).toHaveURL(/\/watchlist/)

  const cookiesBefore = await context.cookies()
  expect(cookiesBefore.some((c) => c.name === 'rrsq_session')).toBe(true)
  expect(cookiesBefore.some((c) => c.name === 'rrsq_csrf')).toBe(true)

  await context.clearCookies({ name: 'rrsq_session' })
  const cookiesAfter = await context.cookies()
  expect(cookiesAfter.some((c) => c.name === 'rrsq_session')).toBe(false)
  expect(cookiesAfter.some((c) => c.name === 'rrsq_csrf')).toBe(true) // left in place, as instructed

  // A real navigation to the same protected route: the app has to fetch to render it, that
  // fetch now 401s for real, and AuthContext's own reaction (not a stub) drives the
  // redirect.
  await page.goto('watchlist')

  await expect(page).toHaveURL(/\/login\?next=%2Fwatchlist/, { timeout: 30_000 })
  await expect(page.locator('#login-username')).toBeVisible()
})
