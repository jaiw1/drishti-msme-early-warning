// One way to put a screen on the page in a test.
//
// Every screen sits inside four providers in the real app (toasts, router, auth, error
// boundary). A test that assembles them by hand tests a different app from the one that
// ships, so this is the only assembly.

import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { ToastProvider } from '../components/Toasts'

const ROUTER_FLAGS = { v7_startTransition: true, v7_relativeSplatPath: true }

/** A session envelope as `GET /auth/me` returns one. */
export const session = (role = 'credit_officer', extra = {}) => ({
  username: `${role}.demo`,
  full_name: `Demo ${role}`,
  role,
  ein: 'EIN-100000',
  scope: role === 'credit_officer' ? ['MSME-CC', 'MSME-TL', 'LAP'] : [],
  must_change_password: false,
  csrf_token: 'csrf-test',
  expires_at: new Date(Date.now() + 3600_000).toISOString(),
  ...extra,
})

export function renderScreen(ui, { path = '/', mode = 'live', user = session('manager') } = {}) {
  return render(
    <ToastProvider timeoutMs={0}>
      <AuthProvider initialMode={mode} initialUser={mode === 'static' ? null : user}>
        <MemoryRouter initialEntries={[path]} future={ROUTER_FLAGS}>
          {ui}
        </MemoryRouter>
      </AuthProvider>
    </ToastProvider>,
  )
}

export default renderScreen
