// Portfolio risk & impact — where the risk sits, and what acting early is worth.

import AppShell from '../components/AppShell'
import PortfolioRisk from '../components/PortfolioRisk'
import AccountDetail from '../components/AccountDetail'
import ErrorState from '../components/states/ErrorState'
import Loading from '../components/states/Loading'
import Empty from '../components/states/Empty'
import { useAuth } from '../auth/AuthContext'
import useAsync from '../lib/useAsync'
import { loadMetrics, loadWholeBook } from '../data/drishti'
import { badgeForMode } from '../data/provenance'
import { useSearchParams } from 'react-router-dom'

export default function PortfolioRiskScreen() {
  const { isStatic } = useAuth()
  const live = !isStatic
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
        <PortfolioRisk
          rows={book.data}
          summary={metrics.data?.summary}
          ecosystem={metrics.data?.ecosystem ?? book.meta?.ecosystem}
          rankOrder={metrics.data?.metrics?.rank_order}
          thresholds={book.meta?.thresholds}
          onSelect={setSelected}
        />
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
