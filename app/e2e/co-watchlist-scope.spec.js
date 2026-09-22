// Spec 1 — credit officer scope.
//
// s.kulkarni is scoped to MSME-CC / MSME-TL / LAP (rrsquad-platform/seeds/users.yaml). The
// server enforces that scope (GET /drishti/portfolio only ever returns those portfolios
// for this user — nothing is filtered client-side); this spec checks the UI tells the
// truth about it: only scoped rows on screen, the scope stated in one line, and every
// screen outside the officer's role rendering <PermissionDenied/> rather than its content.
import { test, expect } from '@playwright/test'
import { signIn } from './helpers/auth.js'
import { USERS } from './helpers/users.js'

test.describe('credit officer scope', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, USERS.creditOfficer.username)
    await expect(page).toHaveURL(/\/watchlist/)
  })

  test('watch-list shows only the officer\'s scoped portfolios and states the scope', async ({ page }) => {
    await expect(page.getByTestId('state-loading')).toHaveCount(0)

    // The scope line names exactly the officer's portfolios.
    const scopeBanner = page.getByText(/Showing only your portfolios/i)
    await expect(scopeBanner).toBeVisible()
    for (const portfolio of USERS.creditOfficer.scope) {
      await expect(scopeBanner).toContainText(portfolio)
    }

    // Every row's Portfolio column is one of the scoped portfolios — nothing outside it
    // leaked through, and the table actually has rows to check.
    const table = page.getByRole('table')
    await expect(table).toBeVisible()
    const portfolioCells = table.locator('tbody tr td:nth-child(2)')
    const count = await portfolioCells.count()
    expect(count).toBeGreaterThan(0)
    const seen = new Set()
    for (let i = 0; i < count; i += 1) {
      seen.add((await portfolioCells.nth(i).innerText()).trim())
    }
    for (const portfolio of seen) {
      expect(USERS.creditOfficer.scope).toContain(portfolio)
    }

    // The portfolio filter itself only offers the scoped portfolios, not the full list.
    const filterOptions = await page.locator('#f-portfolio option').allInnerTexts()
    const offeredPortfolios = filterOptions.filter((t) => t !== 'All portfolios')
    for (const portfolio of offeredPortfolios) {
      expect(USERS.creditOfficer.scope).toContain(portfolio)
    }
  })

  test('/threshold renders permission-denied, not the threshold editor', async ({ page }) => {
    await page.goto('threshold')
    await expect(page.getByTestId('state-denied')).toBeVisible()
    await expect(page.getByTestId('threshold-dialog')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /change thresholds/i })).toHaveCount(0)
  })

  test('/admin renders permission-denied, not the admin console', async ({ page }) => {
    await page.goto('admin')
    await expect(page.getByTestId('state-denied')).toBeVisible()
    await expect(page.getByText(/users and roles/i)).toHaveCount(0)
    await expect(page.getByTestId('create-user-dialog')).toHaveCount(0)
  })

  // The three screens the role-scoping pass took away from a credit officer. The server
  // refuses metaSync / metaProvenance / drishtiValidation independently; this is the half
  // that makes a typed URL an explanation rather than a blank page.
  for (const path of ['data-sources', 'model', 'real-data']) {
    test(`/${path} renders permission-denied, not the screen`, async ({ page }) => {
      await page.goto(path)
      await expect(page.getByTestId('state-denied')).toBeVisible()
      await expect(page.getByTestId('state-denied')).toContainText('Credit officer')
    })
  }

  test('the navigation offers only the two screens that remain', async ({ page }) => {
    const links = page.getByRole('navigation', { name: 'Sections' }).first().getByRole('link')
    await expect(links).toHaveText(['Watch-list', 'Portfolio risk'])
  })

  test('portfolio risk carries no provisioning what-if for an officer', async ({ page }) => {
    await page.goto('risk')
    await expect(page.getByRole('heading', { name: /by lending portfolio/i })).toBeVisible()
    await expect(page.getByLabel('Accounts cured by acting early')).toHaveCount(0)
    await expect(page.getByText(/provisioning what-if/i)).toHaveCount(0)
  })
})
