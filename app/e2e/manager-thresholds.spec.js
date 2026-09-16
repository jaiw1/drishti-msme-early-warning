// Spec 2 — manager: forced password change on the way in, then a threshold change.
//
// r.venkataraman comes out of global-setup.js on must_change_password (every seed user
// does), so simply signing in here already exercises that gate — this spec asserts it
// explicitly rather than just tolerating it. It then drives the real "Change thresholds"
// dialog end to end: fill, confirm, the audited toast, the new row in the change-history
// table, and — the part that makes the "no score row was modified" claim visible — the
// watch-list showing a row's *recomputed* band next to the *published* one once they
// differ.
//
// The new Red/Amber values are computed from whatever is currently in force (read off the
// screen), not hardcoded, so the test works no matter what an earlier run — or another
// lane's own poking at the same screen — left the thresholds at.
import { test, expect } from '@playwright/test'
import { signIn } from './helpers/auth.js'
import { USERS } from './helpers/users.js'

const JUSTIFICATION = 'e2e suite: tightening both lines to exercise the audited change-and-recompute path.'

test('manager completes the forced password change, then moves and audits a threshold', async ({ page }) => {
  test.setTimeout(120_000)

  // --- forced password change, exercised explicitly --------------------------------------
  // r.venkataraman is untouched by every other spec, and global-setup.js resets every seed
  // user right before this runs, so this should always take the forced-change leg — assert
  // that rather than merely tolerating whichever one happens.
  const outcome = await signIn(page, USERS.manager.username)
  expect(outcome).toBe('forced-change')
  await expect(page).toHaveURL(/\/watchlist/)

  // --- open Thresholds and read what is currently in force --------------------------------
  await page.goto('threshold')
  await expect(page.getByTestId('state-loading')).toHaveCount(0)
  const redNowText = await page.locator('text=Red — act now').locator('..').locator('.text-3xl').innerText()
  const amberNowText = await page.locator('text=Amber — watch').locator('..').locator('.text-3xl').innerText()
  const redNow = parseFloat(redNowText)
  const amberNow = parseFloat(amberNowText)
  expect(Number.isFinite(redNow)).toBe(true)
  expect(Number.isFinite(amberNow)).toBe(true)

  // A large, deliberate move — guarantees plenty of accounts cross from their published
  // band into the recomputed one, whatever the starting point was.
  const newRed = Math.max(5, redNow - 25)
  const newAmber = Math.max(2, Math.min(amberNow - 10, newRed - 2))

  // --- change thresholds --------------------------------------------------------------
  await page.getByRole('button', { name: /change thresholds/i }).click()
  const dialog = page.getByTestId('threshold-dialog')
  await expect(dialog).toBeVisible()

  await page.locator('#thr-red').fill(String(newRed))
  await page.locator('#thr-amber').fill(String(newAmber))
  await page.locator('#thr-why').fill(JUSTIFICATION)
  await page.getByRole('button', { name: /confirm and apply/i }).click()

  // --- confirmation toast ---------------------------------------------------------------
  const toast = page.getByTestId('toast-region')
  await expect(toast).toContainText(/thresholds changed to/i, { timeout: 30_000 })
  await expect(toast).toContainText(/recorded in the append-only audit log/i)
  await expect(dialog).toHaveCount(0)

  // --- the change lands in the history table --------------------------------------------
  const historyTable = page.getByRole('table').last()
  await expect(historyTable).toContainText(JUSTIFICATION, { timeout: 15_000 })

  // The headline figures on the page now read back the new thresholds.
  await expect(page.locator('text=Red — act now').locator('..').locator('.text-3xl'))
    .toContainText(newRed.toFixed(0))

  // --- watch-list: published band beside the recomputed one, where they differ ----------
  await page.goto('watchlist?bucket=red')
  await expect(page.getByTestId('state-loading')).toHaveCount(0)
  await expect(
    page.getByText(/Band.*is recomputed against the thresholds in force right now/i),
  ).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/^published\s/).first()).toBeVisible()
})
