// Routes and the app shell.
//
// The four cockpit tabs became routes without changing their contents: the point of this
// lane is that a screen is addressable, guarded, and announced — not that it looks
// different. Everything protected sits behind <RequireAuth>, which in static-demo mode
// passes straight through because there is no backend to authenticate against.

import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import RequireAuth from './auth/RequireAuth'
import RequireRole from './auth/RequireRole'
import { ROLE } from './auth/roles'
import { useAuth } from './auth/AuthContext'
import ErrorBoundary from './components/ErrorBoundary'
import RouteAnnouncer from './components/RouteAnnouncer'
import SkipLink from './components/SkipLink'
import StaticDemoBanner from './components/StaticDemoBanner'
import Empty from './components/states/Empty'
import Loading from './components/states/Loading'
import Admin from './screens/Admin'
import ChangePassword from './screens/ChangePassword'
import Cockpit, { PATH_BY_VIEW } from './screens/Cockpit'
import Login from './screens/Login'

/** ?view=risk was how the old tab switcher deep-linked. Keep those links alive. */
function LegacyViewRedirect() {
  const location = useLocation()
  const view = new URLSearchParams(location.search).get('view')
  const target = PATH_BY_VIEW[view] || '/watchlist'
  const params = new URLSearchParams(location.search)
  params.delete('view')
  const search = params.toString()
  return <Navigate to={{ pathname: target, search: search ? `?${search}` : '' }} replace />
}

export default function App() {
  const { ready, isStatic } = useAuth()

  return (
    <>
      <SkipLink />
      {isStatic && <StaticDemoBanner />}
      <RouteAnnouncer />
      {!ready ? (
        <div className="grid min-h-screen place-items-center bg-slate-100">
          <Loading label="Starting DRISHTi…" inline />
        </div>
      ) : (
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<LegacyViewRedirect />} />
            <Route path="/login" element={<Login />} />
            <Route path="/change-password" element={<RequireAuth><ChangePassword /></RequireAuth>} />
            <Route path="/watchlist" element={<RequireAuth><Cockpit /></RequireAuth>} />
            <Route path="/risk" element={<RequireAuth><Cockpit /></RequireAuth>} />
            <Route path="/model" element={<RequireAuth><Cockpit /></RequireAuth>} />
            <Route path="/real-data" element={<RequireAuth><Cockpit /></RequireAuth>} />
            <Route
              path="/admin"
              element={<RequireRole allow={[ROLE.ADMIN]}><Admin /></RequireRole>}
            />
            <Route
              path="*"
              element={
                <main id="main-content" className="grid min-h-screen place-items-center bg-slate-100 px-6">
                  <div className="w-full max-w-md">
                    <Empty
                      title="That page does not exist"
                      hint="The link may be from an older build. Use the sidebar to get back to the watch-list."
                    />
                  </div>
                </main>
              }
            />
          </Routes>
        </ErrorBoundary>
      )}
    </>
  )
}
