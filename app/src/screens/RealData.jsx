// Real-data validation — the same method on real Indian MSMEs.
//
// The payload is bundled with the build rather than served by the platform: it is a
// one-off offline study, not a published model run, and pretending otherwise would put a
// BANK_API badge on a number the bank never produced.

import AppShell from '../components/AppShell'
import RealModel from '../components/RealModel'
import Empty from '../components/states/Empty'
import Loading from '../components/states/Loading'
import { useAuth } from '../auth/AuthContext'
import useAsync from '../lib/useAsync'
import { loadMetrics, loadRealDataModel } from '../data/drishti'
import { SOURCE } from '../components/SourceBadge'

export default function RealData() {
  const { isStatic } = useAuth()
  const live = !isStatic
  const real = useAsync(({ signal }) => loadRealDataModel({ live, signal }), [live])
  const metrics = useAsync(({ signal }) => loadMetrics({ live, signal }), [live])

  return (
    <AppShell
      view="real"
      title="Real-Data Validation"
      subtitle="The same method, proven on real Indian MSMEs"
      help="real"
      source={SOURCE.SIMULATED}
      sourceDetail="An offline study bundled with this build. It is not a published model run, and the bank did not produce these numbers."
    >
      {real.loading ? (
        <Loading label="Loading the real-data study…" />
      ) : real.error || !real.data ? (
        <Empty
          title="The real-data study is not in this build"
          hint="public/real_model.json is optional; without it the synthetic results stand on their own and this page claims nothing."
        />
      ) : (
        <RealModel data={real.data} syntheticAuc={metrics.data?.metrics?.auc} />
      )}
    </AppShell>
  )
}
