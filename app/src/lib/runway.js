// Predicted runway: months until the smoothed risk score crosses the next threshold,
// projected from a least-squares fit of the recent trend. Uses ONLY information visible
// at "today" (never the ground-truth outcome). Validated offline on the synthetic book:
// median error ≈3 months — a directional horizon for prioritisation, not a promise.

function lsqSlope(vals) {
  const n = vals.length
  const xm = (n - 1) / 2
  const ym = vals.reduce((a, b) => a + b, 0) / n
  let num = 0, den = 0
  for (let i = 0; i < n; i++) { num += (i - xm) * (vals[i] - ym); den += (i - xm) ** 2 }
  return num / den
}

export function runwayEstimate(timeline, refMonth, redThr) {
  if (!timeline?.length) return null
  const hist = timeline.filter((p) => p.date <= refMonth).map((p) => p.pd_smooth ?? p.pd)
  if (hist.length < 7) return null
  const vals = hist.slice(-6)
  const cur = vals[vals.length - 1]
  const slope = lsqSlope(vals)
  if (slope <= 0.002) return { months: null, rising: false }
  const target = cur < redThr ? redThr : 0.85
  const months = Math.max(1, Math.min(12, Math.ceil((target - cur) / slope)))
  return { months, rising: true, toCritical: cur >= redThr }
}
