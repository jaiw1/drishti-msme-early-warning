// axe-core a11y scans across every screen.
//
// Fails on any `serious`/`critical` violation (helpers/axe.js); moderate/minor violations
// are printed to the run log for the report but do not fail the suite. Authenticated
// screens all scan under one admin session (roles A/M/CO/RM all see a strict subset of
// what an admin does, and login/change-password/threshold history/admin roles are already
// covered by the role-specific specs) — a shared session so this file isn't paying for a
// fresh argon2id login per screen.
import { test, expect } from '@playwright/test'
import { fillLogin, gotoLogin, signIn } from './helpers/auth.js'
import { FINAL_PASSWORD, SEED_INITIAL_PASSWORD, USERS } from './helpers/users.js'
import { scanAndAssert } from './helpers/axe.js'

test('a11y: /login', async ({ page }) => {
  await gotoLogin(page)
  await expect(page.locator('#login-username')).toBeVisible()
  await scanAndAssert(page, '/login')
})

test('a11y: /change-password (forced-change gate)', async ({ page }) => {
  // v.rathore is fresh out of global-setup.js at this point in the run (this is the only
  // spec that signs in as this user before admin-operations.spec.js later targets them
  // for its role/deactivate/reset ops, which don't need to know their password).
  await gotoLogin(page)
  await fillLogin(page, USERS.relationshipManager1.username, SEED_INITIAL_PASSWORD)
  await expect(page).toHaveURL(/\/change-password/, { timeout: 30_000 })
  await scanAndAssert(page, '/change-password')

  // Complete it, so this user is left in a normal state rather than stuck mid-flow.
  await page.locator('#cp-current').fill(SEED_INITIAL_PASSWORD)
  await page.locator('#cp-new').fill(FINAL_PASSWORD)
  await page.locator('#cp-confirm').fill(FINAL_PASSWORD)
  await page.getByRole('button', { name: /change password/i }).click()
  await expect(page).not.toHaveURL(/\/change-password/, { timeout: 30_000 })
})

test.describe.serial('a11y: authenticated screens', () => {
  /** @type {import('@playwright/test').Page} */
  let page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await signIn(page, USERS.admin.username)
  })

  test.afterAll(async () => {
    await page?.close()
  })

  test('/watchlist', async () => {
    await page.goto('watchlist')
    await scanAndAssert(page, '/watchlist')
  })

  test('/watchlist with an account drawer open', async () => {
    await page.goto('watchlist')
    await page.getByTestId('state-loading').waitFor({ state: 'detached', timeout: 20_000 }).catch(() => {})
    await page.getByRole('table').locator('tbody tr').first().click()
    await expect(page.getByTestId('account-detail')).toBeVisible({ timeout: 20_000 })
    await scanAndAssert(page, '/watchlist (account drawer open)')
  })

  test('/risk', async () => {
    await page.goto('risk')
    await scanAndAssert(page, '/risk')
  })

  test('/model', async () => {
    await page.goto('model')
    await scanAndAssert(page, '/model')
  })

  test('/threshold', async () => {
    await page.goto('threshold')
    await scanAndAssert(page, '/threshold')
  })

  test('/data-sources', async () => {
    await page.goto('data-sources')
    await scanAndAssert(page, '/data-sources')
  })

  test('/admin', async () => {
    await page.goto('admin')
    await scanAndAssert(page, '/admin')
  })

  test('/real-data', async () => {
    await page.goto('real-data')
    await scanAndAssert(page, '/real-data')
  })
})
