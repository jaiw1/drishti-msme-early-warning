// Indian-currency + misc formatters used across the cockpit.

export function inr(n) {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  const v = Number(n)
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`
  return `₹${Math.round(v).toLocaleString('en-IN')}`
}

export const pct = (x, d = 0) => (x == null || !Number.isFinite(Number(x)) ? '—' : `${(Number(x) * 100).toFixed(d)}%`)

// `text` is the accessible variant (≥ 4.5:1 on white and on `soft`); `bg`/`dot` are the
// brand fills, which are decorative and exempt from the text-contrast rule.
export const RAG = {
  red: { label: 'Red', text: 'text-rag-redtx', bg: 'bg-rag-red', soft: 'bg-red-50 text-rag-redtx border-red-200', dot: 'bg-rag-red' },
  amber: { label: 'Amber', text: 'text-rag-ambertx', bg: 'bg-rag-amber', soft: 'bg-amber-50 text-rag-ambertx border-amber-200', dot: 'bg-rag-amber' },
  green: { label: 'Green', text: 'text-rag-greentx', bg: 'bg-rag-green', soft: 'bg-green-50 text-rag-greentx border-green-200', dot: 'bg-rag-green' },
}
