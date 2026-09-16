// The four numbers a credit officer reads first.
//
// These come from the published run's own summary, not from whatever rows happen to be on
// screen: a band count that changed when you paged through the watch-list would describe
// the page, not the book.

import { CircleCheck, Clock, ShieldAlert, TriangleAlert } from 'lucide-react'
import { inr } from '../lib/format'

function Card({ icon: Icon, tint, value, label, sub }) {
  return (
    <div className="flex-1 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-3">
        <div className={`grid h-10 w-10 place-items-center rounded-lg ${tint}`}>
          <Icon size={20} aria-hidden="true" />
        </div>
        <div>
          <div className="text-2xl font-extrabold leading-none text-slate-900">{value}</div>
          <div className="mt-1 text-xs text-slate-600">{label}</div>
        </div>
      </div>
      {sub && <div className="mt-2 text-xs text-slate-600">{sub}</div>}
    </div>
  )
}

const count = (v) => (v == null ? '—' : Number(v).toLocaleString('en-IN'))

export default function Kpis({ summary, metrics }) {
  if (!summary) return null
  const total = summary.total_accounts
  const lead = metrics?.median_first_warning_months
  const early = metrics?.pct_flagged_6mo_ahead
  return (
    <div className="flex flex-col gap-3 sm:flex-row">
      <Card
        icon={ShieldAlert}
        tint="bg-red-50 text-rag-redtx"
        value={count(summary.red)}
        label="Red — act now"
        sub={summary.exposure_at_risk != null ? `${inr(summary.exposure_at_risk)} exposure at risk` : undefined}
      />
      <Card icon={TriangleAlert} tint="bg-amber-50 text-rag-ambertx" value={count(summary.amber)} label="Amber — watch" sub="Early-warning tier" />
      <Card
        icon={CircleCheck}
        tint="bg-green-50 text-rag-greentx"
        value={count(summary.green)}
        label="Green — healthy"
        sub={total != null ? `of ${count(total)} scored accounts` : undefined}
      />
      <Card
        icon={Clock}
        tint="bg-idbi-green/10 text-idbi-green"
        value={lead == null ? '—' : `${lead} mo`}
        label="Median early warning"
        sub={early == null ? undefined : `${Math.round(early * 100)}% flagged ≥6 months ahead`}
      />
    </div>
  )
}
