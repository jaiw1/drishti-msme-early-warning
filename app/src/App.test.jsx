import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './auth/AuthContext'
import { jsonResponse, mockFetchRoutes, networkFailure } from './test/http'
import demoData from './test/fixtures/demo_data.min.json'

const ROUTER_FLAGS = { v7_startTransition: true, v7_relativeSplatPath: true }

const SESSION = (role = 'credit_officer') => ({
  username: `${role}.demo`, full_name: `Demo ${role}`, role, scope: [],
  must_change_password: false, csrf_token: 'c',
  expires_at: new Date(Date.now() + 3600_000).toISOString(),
})

function renderApp(path, { mode = 'live', user = null } = {}) {
  return render(
    <AuthProvider initialMode={mode} initialUser={user}>
      <MemoryRouter initialEntries={[path]} future={ROUTER_FLAGS}>
        <App />
      </MemoryRouter>
    </AuthProvider>,
  )
}

const demoRoutes = {
  '/demo_data.json': jsonResponse(200, demoData),
  '/real_model.json': () => { throw networkFailure() },
}

afterEach(() => vi.unstubAllGlobals())

describe('App shell', () => {
  it('offers a skip link as the first tab stop', () => {
    mockFetchRoutes(demoRoutes)
    renderApp('/login')
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute('href', '#main-content')
  })

  it('sends an anonymous visitor at the root to the sign-in screen', async () => {
    mockFetchRoutes(demoRoutes)
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('keeps ?view= deep links from the old tab switcher working', async () => {
    mockFetchRoutes(demoRoutes)
    renderApp('/?view=risk', { user: SESSION('manager') })
    expect(await screen.findByRole('heading', { name: /Portfolio Risk/i })).toBeInTheDocument()
  })

  it('renders the cockpit for a signed-in credit officer, with the session bar', async () => {
    mockFetchRoutes(demoRoutes)
    renderApp('/watchlist', { user: SESSION() })

    expect(await screen.findByRole('heading', { name: /Borrower Watch-list/i })).toBeInTheDocument()
    expect(screen.getByTestId('session-bar')).toHaveTextContent('Demo credit_officer')
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Simulated' })).toBeInTheDocument()
  })

  it('refuses /admin to a credit officer and says why', async () => {
    mockFetchRoutes(demoRoutes)
    renderApp('/admin', { user: SESSION() })
    expect(await screen.findByTestId('state-denied')).toHaveTextContent('Administrator')
  })

  it('runs without a backend, and says on screen that it is doing so', async () => {
    mockFetchRoutes(demoRoutes)
    renderApp('/watchlist', { mode: 'static' })

    expect(screen.getByTestId('static-demo-banner')).toHaveTextContent('No backend answered')
    expect(await screen.findByRole('heading', { name: /Borrower Watch-list/i })).toBeInTheDocument()
    // no session bar sign-out in static mode: there is no session to end
    expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument()
  })

  it('shows the shared error state when the snapshot cannot be loaded', async () => {
    mockFetchRoutes({ ...demoRoutes, '/demo_data.json': () => { throw networkFailure() } })
    renderApp('/watchlist', { mode: 'static' })
    await waitFor(() => expect(screen.getByTestId('state-error')).toHaveTextContent('Couldn’t load the portfolio data'))
  })

  it('has a real 404', async () => {
    mockFetchRoutes(demoRoutes)
    renderApp('/nowhere', { user: SESSION() })
    expect(await screen.findByTestId('state-empty')).toHaveTextContent('That page does not exist')
  })
})
