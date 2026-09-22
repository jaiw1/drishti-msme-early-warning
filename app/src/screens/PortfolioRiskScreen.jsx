// Portfolio risk & impact — where the risk sits, and what acting early is worth.

import AppShell from '../components/AppShell'
import PortfolioRisk from '../components/PortfolioRisk'
import AccountDetail from '../components/AccountDetail'
import ErrorState from '../components/states/ErrorState'
import Loading from '../components/states/Loading'
import Empty from '../components/states/Empty'
import { useAuth } from '../auth/AuthContext'
import { roleMatches } from '../auth/roles'
import useAsync from '../lib/useAsync'
import { loadMetrics, loadWholeBook } from '../domain/drishti'
import { policyFoldCost } from '../domain/shapes'
import { badgeForMode } from '../domain/provenance'
import { useSearchParams } from 'react-router-dom'

export default function PortfolioRiskScreen() {
  const { isStatic, roleCode } = useAuth()
  const live = !isStatic
  // The provisioning what-if extrapolates this sample to the whole MSME book under an
  // assumed cure rate. That is a planning exhibit for a manager, not part of a credit
  // officer's working screen — the rest of the screen, scoped to their own portfolios,
  // stays exactly as it was. The frozen bundle shows what a manager sees.
  const showWhatIf = isStatic || roleMatches(roleCode, ['A', 'M'])
  const [params, setParams] = useSearchParams()
  const selected = params.get('account')

  const book = useAsync(({ signal }) => loadWholeBook({ live, signal }), [live])
  const metrics = useAsync(({ signal }) => loadMetrics({ live, signal }), [live])

  const badge = badgeForMode(book.meta?.provenance_mode || metrics.meta?.provenance_mode, book.source)
  const setSelected = (id) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    if (id) next.set('account', id); else next.delete('account')
    return next
  }, { replace: true })

  return (
    <AppShell
      view="risk"
      title="Portfolio Risk & Impact"
      subtitle="Where the risk sits, and what acting early is worth"
      help="risk"
      source={badge.source}
      sandbox={badge.sandbox}
      sourceDetail={badge.detail}
    >
      {book.error ? (
        <ErrorState title="Could not load the book" error={book.error} onRetry={book.reload} />
      ) : book.loading ? (
        <Loading label="Loading the whole book…" />
      ) : (book.data || []).length === 0 ? (
        <Empty title="No accounts in this model run" hint="Nothing has been published for you to see yet." />
      ) : (
        <>
          {book.meta?.truncated && (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-rag-ambertx">
              These exhibits were computed over the first {book.meta.loaded?.toLocaleString('en-IN')} of
              {' '}{book.meta.total?.toLocaleString('en-IN')} accounts, because the browser stops paging at 20,000.
              Read them as a sample of the book, not the whole of it.
            </p>
          )}
          <PortfolioRisk
            rows={book.data}
            summary={metrics.data?.summary}
            ecosystem={metrics.data?.ecosystem ?? book.meta?.ecosystem}
            rankOrder={metrics.data?.metrics?.rank_order}
            policyFold={policyFoldCost(metrics.data?.metrics)}
            thresholds={book.meta?.thresholds}
            showWhatIf={showWhatIf}
            onSelect={setSelected}
          />
        </>
      )}

      {selected && (
        <AccountDetail
          accountId={selected}
          live={live}
          thresholds={book.meta?.thresholds}
          onClose={() => setSelected(null)}
        />
      )}
    </AppShell>
  )
}
