// Spec 3 — administrator: users/roles console, then the audit log.
//
// a.deshmukh exercises all four user-administration operations against v.rathore (an RM
// this suite never itself signs in as, so overwriting their password via "reset" costs
// nothing): set role, deactivate, activate, reset password. Then the audit log: apply a
// filter, verify the hash chain, and read back the intact-chain banner and its row count.
import { test, expect } from '@playwright/test'
import { signIn } from './helpers/auth.js'
import { USERS } from './helpers/users.js'

const TARGET_USERNAME = USERS.relationshipManager1.username // v.rathore

test.describe.serial('administrator operations', () => {
  // Each test signs in fresh via the tolerant helper (see helpers/auth.js) rather than
  // sharing one page across the file — slower under this box's argon2id-under-load cost,
  // but keeps the four operations fully isolated from one another.
  test.beforeEach(async ({ page }) => {
    await signIn(page, USERS.admin.username)
    await page.goto('admin')
    await expect(page.getByTestId('state-loading')).toHaveCount(0)
  })

  // Scoped to the users table specifically: the audit log renders on the same page and,
  // once populated with this file's own actions, its rows can also mention v.rathore
  // (as a target), which would otherwise make this locator ambiguous.
  function targetRow(page) {
    return page.getByRole('table').first().getByRole('row', { name: new RegExp(TARGET_USERNAME) })
  }

  test('set role', async ({ page }) => {
    const row = targetRow(page)
    await expect(row).toBeVisible()
    const roleSelect = row.locator('select')
    const original = await roleSelect.inputValue()
    const other = original === 'credit_officer' ? 'relationship_manager' : 'credit_officer'

    await roleSelect.selectOption(other)
    await expect(page.getByTestId('toast-region')).toContainText(
      new RegExp(`${TARGET_USERNAME} is now`, 'i'),
      { timeout: 30_000 },
    )
    await expect(row.locator('select')).toHaveValue(other)

    // Put it back — this suite should not permanently change a shared demo user's role.
    await roleSelect.selectOption(original)
    await expect(page.getByTestId('toast-region')).toContainText(
      new RegExp(`${TARGET_USERNAME} is now`, 'i'),
      { timeout: 30_000 },
    )
    await expect(row.locator('select')).toHaveValue(original)
  })

  test('deactivate and activate', async ({ page }) => {
    const row = targetRow(page)
    await expect(row).toBeVisible()
    await expect(row).toContainText('Active')

    await row.getByRole('button', { name: /deactivate/i }).click()
    await expect(page.getByTestId('toast-region')).toContainText(
      new RegExp(`${TARGET_USERNAME} deactivated`, 'i'),
      { timeout: 30_000 },
    )
    await expect(row).toContainText('Deactivated')

    await row.getByRole('button', { name: /^activate$/i }).click()
    await expect(page.getByTestId('toast-region')).toContainText(
      new RegExp(`${TARGET_USERNAME} activated`, 'i'),
      { timeout: 30_000 },
    )
    await expect(row).toContainText('Active')
    await expect(row).not.toContainText('Deactivated')
  })

  test('reset password shows a one-time password panel', async ({ page }) => {
    const row = targetRow(page)
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: /reset password/i }).click()

    const resultDialog = page.getByTestId('reset-result')
    await expect(resultDialog).toBeVisible({ timeout: 30_000 })
    await expect(resultDialog).toContainText(new RegExp(`Initial password for ${TARGET_USERNAME}`, 'i'))
    // The one-time value itself: a non-empty monospace string in the panel.
    const passwordText = await resultDialog.locator('p.font-mono').first().innerText()
    expect(passwordText.trim().length).toBeGreaterThan(0)

    await expect(page.getByTestId('toast-region')).toContainText(
      new RegExp(`Password reset for ${TARGET_USERNAME}`, 'i'),
    )

    await resultDialog.getByRole('button', { name: /handed it over/i }).click()
    await expect(resultDialog).toHaveCount(0)

    // The reset also revoked v.rathore's sessions and re-armed must_change_password — the
    // row should say so.
    await expect(row).toContainText(/must change password/i)
  })

  test('audit log: filter, then verify the hash chain', async ({ page }) => {
    await page.locator('#a-actor').fill(USERS.admin.username)
    await page.getByRole('button', { name: /apply filters/i }).click()

    // Filtering to this admin's own actions should show at least the row for whatever
    // this test itself just did signing in / navigating here.
    const auditTable = page.getByRole('table').last()
    await expect(auditTable).toBeVisible({ timeout: 15_000 })

    await page.getByRole('button', { name: /verify chain/i }).click()
    const banner = page.locator('[role="status"][aria-live="polite"]').filter({ hasText: /chain/i })
    await expect(banner).toBeVisible({ timeout: 30_000 })
    await expect(banner).toContainText(/chain intact/i)
    const bannerText = await banner.innerText()
    const rowCountMatch = bannerText.match(/([\d,]+)\s+rows recomputed/i)
    expect(rowCountMatch, `expected a row count in "${bannerText}"`).not.toBeNull()
    expect(Number(rowCountMatch[1].replace(/,/g, ''))).toBeGreaterThan(0)
  })
})
