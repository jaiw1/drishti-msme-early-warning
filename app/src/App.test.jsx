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

  // `/` used to send every role to the watch-list, so a relationship manager — who has no
  // drishti/* operation in the contract — met a permission-denied panel on every sign-in.
  it('lands a relationship manager on a screen their role can open', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/', { user: session('relationship_manager') })
    expect(await screen.findByRole('heading', { name: /Real-Data Validation|Data sources/i })).toBeInTheDocument()
    expect(screen.queryByTestId('state-denied')).not.toBeInTheDocument()
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

  it('signs a relationship manager in from an anonymous root visit and lands them on their home', async () => {
    const user = userEvent.setup()
    mockApi(apiRoutes({ [`POST ${B}/auth/login`]: ok(envelope(session('relationship_manager'))) }), { vi })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Sign in' })
    await signIn(user)
    expect(await screen.findByRole('heading', { name: /Real-Data Validation|Data sources/i })).toBeInTheDocument()
    expect(screen.queryByTestId('state-denied')).not.toBeInTheDocument()
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

  it('offers a credit officer no doors that will not open', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('credit_officer') })
    await screen.findByRole('heading', { name: /Borrower Watch-list/i })
    const nav = screen.getAllByRole('navigation', { name: 'Sections' })[0]
    const labels = [...nav.querySelectorAll('a')].map((a) => a.textContent.trim())
    expect(labels).toContain('Watch-list')
    expect(labels).toContain('Data sources')
    expect(labels).not.toContain('Thresholds')
    expect(labels).not.toContain('Administration')
  })

  it('gives a manager the threshold door and withholds administration', async () => {
    mockApi(apiRoutes(), { vi })
    renderApp('/watchlist', { user: session('manager') })
    await screen.findByRole('heading', { name: /Borrower Watch-list/i })
    const nav = screen.getAllByRole('navigation', { name: 'Sections' })[0]
    const labels = [...nav.querySelectorAll('a')].map((a) => a.textContent.trim())
    expect(labels).toContain('Thresholds')
    expect(labels).not.toContain('Administration')
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
