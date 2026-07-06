import { inr } from '../lib/format'
import { ShieldAlert, TriangleAlert, CircleCheck, IndianRupee, Clock } from 'lucide-react'

function Card({ icon: Icon, tint, value, label, sub }) {
  return (
    <div className="flex-1 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg grid place-items-center ${tint}`}>
          <Icon size={20} />
        </div>
        <div>
          <div className="text-2xl font-extrabold text-slate-900 leading-none">{value}</div>
          <div className="text-xs text-slate-500 mt-1">{label}</div>
        </div>
      </div>
      {sub && <div className="text-xs text-slate-400 mt-2">{sub}</div>}
    </div>
  )
}

export default function Kpis({ summary, metrics }) {
  return (
    <div className="flex flex-col sm:flex-row gap-3">
      <Card icon={ShieldAlert} tint="bg-red-50 text-rag-red" value={summary.red}
            label="Red — act now" sub={`${inr(summary.exposure_at_risk)} exposure at risk`} />
      <Card icon={TriangleAlert} tint="bg-amber-50 text-rag-amber" value={summary.amber}
            label="Amber — watch" sub="Early-warning tier" />
      <Card icon={CircleCheck} tint="bg-green-50 text-rag-green" value={summary.green}
            label="Green — healthy" sub={`of ${summary.total_accounts.toLocaleString('en-IN')} live accounts`} />
      <Card icon={Clock} tint="bg-idbi-green/10 text-idbi-green" value={`${metrics.median_first_warning_months} mo`}
            label="Median early warning" sub={`${Math.round(metrics.pct_flagged_6mo_ahead * 100)}% flagged ≥6 months ahead`} />
    </div>
  )
}
