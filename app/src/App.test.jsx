import { useEffect } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './auth/AuthContext'
import { session } from './test/render'
import { apiRoutes, B, envelope, mockApi, ok } from './test/fixtures/api'
import demoData from './test/fixtures/demo_data.min.json'

const ROUTER_FLAGS = { v7_startTransition: true, v7_relativeSplatPath: true }

/** Reports every location the router settles on, so a test can assert on the URL itself
 *  (not just what ends up on screen) — the root-redirect bug only showed up in `?next=`. */
function LocationSpy({ onChange }) {
  const location = useLocation()
  useEffect(() => onChange(location), [location, onChange])
  return null
}

function renderApp(path, { mode = 'live', user = null, onLocation } = {}) {
  return render(
    <AuthProvider initialMode={mode} initialUser={user}>
      <MemoryRouter initialEntries={[path]} future={ROUTER_FLAGS}>
        {onLocation && <LocationSpy onChange={onLocation} />}
        <App />
      </MemoryRouter>
    </AuthProvider>,
  )
}

const signIn = async (user, username = 'demo') => {
  await user.type(screen.getByLabelText('Username'), username)
  await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
  await user.click(screen.getByRole('button', { name: /sign in/i }))
}

/** The frozen bundle's only network call is the snapshot itself. */
function mockSnapshotOnly({ fail = false } = {}) {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (String(url).endsWith('demo_data.json')) {
      if (fail) throw Object.assign(new TypeError('Failed to fetch'), { name: 'TypeError' })
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => demoData }
    }
    if (String(url).endsWith('real_model.json')) throw new TypeError('Failed to fetch')
    throw new Error(`unexpected fetch ${url}`)
  }))
}

afterEach(() => vi.unstubAllGlobals())

describe('App shell', () => {
  it('offers a skip link as the first tab stop', () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/login')
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute('href', '#main-content')
  })

  // Regression for the root-redirect bug: `/` used to run every visitor — signed in or
  // not — through `homeFor(roleCode, …)`. For a signed-out visitor that has no role, so
  // it fell to homeFor's own last-resort default and landed them on `/data-sources`,
  // which then bounced them to `/login?next=%2Fdata-sources` — a deep link nobody asked
  // for, that a manager who then signed in was sent to instead of the watch-list.
  it('sends an anonymous visitor at the root straight to sign-in, with no next fabricated', async () => {
    mockApi(apiRoutes(), { vi })
    let seen = null
    renderApp('/', { onLocation: (location) => { seen = location } })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(seen).toMatchObject({ pathname: '/login', search: '' })
  })

  it('keeps ?view= deep links from the old tab switcher working', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/?view=risk', { user: session('manager') })
    expect(await screen.findByRole('heading', { name: /Portfolio Risk/i })).toBeInTheDocument()
  })

  // An anonymous ?view= is a genuine deep link (an old bookmark), unlike a bare `/` —
  // it is honoured, and the route guard downstream is what asks the visitor to sign in.
  it('still honours an anonymous ?view= deep link, via a real login next', async () => {
    mockApi(apiRoutes(), { vi })
    let seen = null
    renderApp('/?view=risk', { onLocation: (location) => { seen = location } })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(seen).toMatchObject({ pathname: '/login', search: '?next=%2Frisk' })
  })

  // DRISHTi is a credit product and the RM is SANKET's role. Data sources and the
  // Real-data study used to be open to them; with the first narrowed to A/M and the second
  // to A, there is no DRISHTi screen left for an RM. They land on the watch-list and are
  // told so — inside the shell, so there is still a way to sign out.
  it('tells a relationship manager plainly that DRISHTi has no screen for them', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/', { user: session('relationship_manager') })
    expect(await screen.findByTestId('state-denied')).toHaveTextContent('Relationship manager')
    expect(screen.getByTestId('session-bar')).toBeInTheDocument()
  })

  it('still lands a credit officer on the watch-list', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/', { user: session('credit_officer') })
    expect(await screen.findByRole('heading', { name: /Borrower Watch-list/i })).toBeInTheDocument()
  })

  it('signs a manager in from an anonymous root visit and lands them on the watch-list', async () => {
    const user = userEvent.setup()
    mockApi(apiRoutes({ [`POST ${B}/auth/login`]: ok(envelope(session('manager'))) }), { vi })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Sign in' })
    await signIn(user)
    expect(await screen.findByRole('heading', { name: /Borrower Watch-list/i })).toBeInTheDocument()
  })

  it('signs a relationship manager in from an anonymous root visit and says why there is nothing here', async () => {
    const user = userEvent.setup()
    mockApi(apiRoutes({ [`POST ${B}/auth/login`]: ok(envelope(session('relationship_manager'))) }), { vi })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Sign in' })
    await signIn(user)
    expect(await screen.findByTestId('state-denied')).toHaveTextContent('Relationship manager')
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })

  // A deep link into a specific account must survive the round trip through sign-in,
  // same as any other protected route.
  it('sends an anonymous deep link to an account through login and back to that account', async () => {
    const user = userEvent.setup()
    mockApi(apiRoutes({ [`POST ${B}/auth/login`]: ok(envelope(session('credit_officer'))) }), { vi })
    renderApp('/watchlist?account=MSME00001')
    await screen.findByRole('heading', { name: 'Sign in' })
    await signIn(user)
    expect(await screen.findByRole('dialog', { name: /MSME00001/ })).toBeInTheDocument()
  })

  it('renders the watch-list for a signed-in credit officer, with the session bar', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('credit_officer') })

    expect(await screen.findByRole('heading', { name: /Borrower Watch-list/i })).toBeInTheDocument()
    expect(screen.getByTestId('session-bar')).toHaveTextContent('Demo credit_officer')
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })

  it('refuses /admin to a credit officer and says why', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/admin', { user: session('credit_officer') })
    expect(await screen.findByTestId('state-denied')).toHaveTextContent('Administrator')
  })

  it('refuses /threshold to a credit officer — the route’s x-roles are M and A', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/threshold', { user: session('credit_officer') })
    expect(await screen.findByTestId('state-denied')).toHaveTextContent('Credit officer')
  })

  it('lets a manager into /threshold', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/threshold', { user: session('manager') })
    expect(await screen.findByRole('heading', { name: 'Risk thresholds' })).toBeInTheDocument()
  })

  /** Every link the signed-in role is offered, in the order the sidebar offers them. */
  const navLabels = () => {
    const nav = screen.getAllByRole('navigation', { name: 'Sections' })[0]
    return [...nav.querySelectorAll('a')].map((a) => a.textContent.trim())
  }

  it('offers a credit officer no doors that will not open', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('credit_officer') })
    await screen.findByRole('heading', { name: /Borrower Watch-list/i })
    expect(navLabels()).toEqual(['Watch-list', 'Portfolio risk'])
  })

  it('gives a manager the threshold and data-source doors and withholds administration', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('manager') })
    await screen.findByRole('heading', { name: /Borrower Watch-list/i })
    const labels = navLabels()
    expect(labels).toEqual(['Watch-list', 'Portfolio risk', 'Model & Metrics', 'Thresholds', 'Data sources'])
    expect(labels).not.toContain('Administration')
    expect(labels).not.toContain('Real-data model')
  })

  it('gives an administrator every door, the two admin-only ones included', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('admin') })
    await screen.findByRole('heading', { name: /Borrower Watch-list/i })
    expect(navLabels()).toEqual([
      'Watch-list', 'Real-data modelREAL', 'Portfolio risk', 'Model & Metrics',
      'Thresholds', 'Data sources', 'Administration',
    ])
  })

  it('offers a relationship manager no doors at all, and says so', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('relationship_manager') })
    await screen.findByTestId('state-denied')
    expect(navLabels()).toEqual([])
  })

  // The three screens whose audience narrowed. A typed URL must land on the refusal, not
  // on a blank page and not on the screen — and the backend refuses the data independently,
  // which tests/test_rbac.py in rrsquad-platform asserts from the other end.
  describe.each([
    ['/data-sources', 'credit_officer', 'Credit officer'],
    ['/data-sources', 'relationship_manager', 'Relationship manager'],
    ['/model', 'credit_officer', 'Credit officer'],
    ['/model', 'relationship_manager', 'Relationship manager'],
    ['/real-data', 'credit_officer', 'Credit officer'],
    ['/real-data', 'manager', 'Manager'],
    ['/real-data', 'relationship_manager', 'Relationship manager'],
  ])('a direct visit to %s as a %s', (path, role, label) => {
    it('is refused, by name, inside the shell', async () => {
      mockApi(apiRoutes(), { vi })
      renderApp(path, { user: session(role) })
      expect(await screen.findByTestId('state-denied')).toHaveTextContent(label)
      expect(screen.getByTestId('session-bar')).toBeInTheDocument()
    })
  })

  describe.each([
    ['/data-sources', 'manager', /Data sources & sync/i],
    ['/data-sources', 'admin', /Data sources & sync/i],
    ['/model', 'manager', /Model|Metrics/i],
    ['/real-data', 'admin', /Real-Data Validation/i],
  ])('a direct visit to %s as a %s', (path, role, heading) => {
    it('opens the screen', async () => {
      mockApi(apiRoutes(), { vi })
      renderApp(path, { user: session(role) })
      expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
      expect(screen.queryByTestId('state-denied')).not.toBeInTheDocument()
    })
  })

  // Static mode has no session and therefore no role. It shows what a manager sees, minus
  // the screens that are an administrator's alone — the navigation and a typed URL agree.
  it('shows the static demo a manager’s navigation, minus the admin-only screens', async () => {
    mockSnapshotOnly()
    renderApp('/watchlist', { mode: 'static' })
    await screen.findByRole('heading', { name: /Borrower Watch-list/i })
    const labels = navLabels()
    expect(labels).toContain('Data sources')
    expect(labels).not.toContain('Real-data model')
    expect(labels).not.toContain('Administration')
    expect(labels).not.toContain('Thresholds')
  })

  it('refuses the admin-only screens in static mode too, rather than rendering them', async () => {
    mockSnapshotOnly()
    renderApp('/real-data', { mode: 'static' })
    expect(await screen.findByTestId('state-empty')).toHaveTextContent('not in the static demo')
  })

  it('runs without a backend, and says on screen that it is doing so', async () => {
    mockSnapshotOnly()
    renderApp('/watchlist', { mode: 'static' })

    expect(screen.getByTestId('static-demo-banner')).toHaveTextContent('No backend answered')
    expect(await screen.findByRole('heading', { name: /Borrower Watch-list/i })).toBeInTheDocument()
    // no session bar sign-out in static mode: there is no session to end
    expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument()
  })

  it('shows the shared error state when the snapshot cannot be loaded', async () => {
    mockSnapshotOnly({ fail: true })
    renderApp('/watchlist', { mode: 'static' })
    await waitFor(() => expect(screen.getByTestId('state-error')).toHaveTextContent('Could not load the watch-list'))
  })

  it('has a real 404', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/nowhere', { user: session('manager') })
    expect(await screen.findByTestId('state-empty')).toHaveTextContent('That page does not exist')
  })

  it('traps a user who must change their password on the change-password screen', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('manager', { must_change_password: true }) })
    expect(await screen.findByRole('heading', { name: /password/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Borrower Watch-list/i })).not.toBeInTheDocument()
  })
})
