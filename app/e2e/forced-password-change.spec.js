// Spec 5 — a must_change_password user is trapped on /change-password.
//
// p.nair comes out of global-setup.js on must_change_password + the seed password, and
// this spec deliberately does NOT complete the change (that path is exercised for real by
// manager-thresholds.spec.js instead) — it signs in and stops there, so it can assert the
// trap itself: stuck on /change-password, and typing /watchlist in the address bar lands
// back on /change-password rather than the watch-list, even though p.nair (a relationship
// manager) would be denied /watchlist anyway once authenticated — RequireAuth's
// must-change-password gate has to win *before* any role check runs, not after.
import { test, expect } from '@playwright/test'
import { fillLogin, gotoLogin } from './helpers/auth.js'
import { SEED_INITIAL_PASSWORD, USERS } from './helpers/users.js'

test('a must_change_password user cannot reach the app until they change it', async ({ page }) => {
  await gotoLogin(page)
  await fillLogin(page, USERS.relationshipManager2.username, SEED_INITIAL_PASSWORD)
  await expect(page).toHaveURL(/\/change-password/, { timeout: 30_000 })
  await expect(page.getByText(/choose a new password to continue/i)).toBeVisible()

  // Typing a deep link to a protected screen redirects straight back to the gate.
  await page.goto('watchlist')
  await expect(page).toHaveURL(/\/change-password/, { timeout: 30_000 })

  // Same for a screen this role would not even be allowed into once authenticated — the
  // password-change gate has to be checked first, before the role check ever runs.
  await page.goto('admin')
  await expect(page).toHaveURL(/\/change-password/, { timeout: 30_000 })

  // The form itself is still there and usable — this is a gate, not a dead end.
  await expect(page.locator('#cp-current')).toBeVisible()
  await expect(page.locator('#cp-new')).toBeVisible()
  await expect(page.locator('#cp-confirm')).toBeVisible()
})
