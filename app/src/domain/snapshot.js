// The bundled snapshot, and the views over it that stand in for the API.
//
// `deploy/export_static.py` freezes a build with no `VITE_API_BASE`; that build has to
// open and show real DRISHTi numbers with no backend at all. Every loader in `drishti.js`
// falls through to one of these when the app is in static mode, so a screen never learns
// which mode it is in — it asks for a watch-list and gets one.
//
// The snapshot is ~10 MB, so it is fetched once and memoised for the life of the page.

import { publicPath } from '../lib/basepath'
import { runwayEstimate } from '../lib/runway'

let snapshotPromise = null
let realModelPromise = null

async function fetchJson(file, signal) {
  const response = await fetch(publicPath(file), { signal })
  if (!response.ok) throw new Error(`Could not load ${file} (HTTP ${response.status})`)
  return response.json()
}

/** The whole snapshot, fetched at most once. A failure is not cached. */
export function loadSnapshot(signal) {
  if (!snapshotPromise) {
    snapshotPromise = fetchJson('demo_data.json', signal)
      .then((data) => {
        const ref = data.meta?.reference_month
        const red = data.portfolio_summary?.red_thr
        for (const row of data.portfolio || []) {
          row.runway = row.bucket === 'green'
            ? null
            : runwayEstimate(data.timelines?.[row.account_id], ref, red)
        }
        return data
      })
      .catch((error) => { snapshotPromise = null; throw error })
  }
  return snapshotPromise
}

/** The real-MSME validation payload. Optional: the screen degrades without it. */
export function loadRealModel(signal) {
  if (!realModelPromise) {
    realModelPromise = fetchJson('real_model.json', signal)
      .catch((error) => { realModelPromise = null; throw error })
  }
  return realModelPromise
}

export function resetSnapshotCache() {
  snapshotPromise = null
  realModelPromise = null
}

/** The snapshot's thresholds, in the API's spelling. */
export function snapshotThresholds(snapshot) {
  const summary = snapshot?.portfolio_summary || {}
  return {
    red_thr: summary.red_thr ?? null,
    amber_thr: summary.amber_thr ?? null,
    source: 'model_run',
    published_red_thr: summary.red_thr ?? null,
    published_amber_thr: summary.amber_thr ?? null,
    changed_at: null,
    change_id: null,
    justification: null,
    cost_model: snapshot?.metrics?.cost_model ?? null,
    history: [],
    editable_by: ['M', 'A'],
  }
}

/** One account, in the API's `drishtiAccount` shape. */
export function snapshotAccount(snapshot, accountId) {
  const row = (snapshot?.portfolio || []).find((r) => r.account_id === accountId)
  if (!row) return null
  const thresholds = snapshotThresholds(snapshot)
  return {
    ...row,
    id: row.account_id,
    scores: {
      pd: row.pd,
      pd_smooth: row.pd_smooth ?? null,
      pd_calibrated: null,
      bucket: row.bucket,
      published_bucket: row.bucket,
      reasons: row.reasons || [],
      first_warning_lead: row.first_warning_lead ?? null,
      runway_months: row.runway?.months ?? null,
      sma2_within_6m: null,
    },
    thresholds: { red_thr: thresholds.red_thr, amber_thr: thresholds.amber_thr },
    channels_present: row.channels_present || [],
    provenance_badges: {
      families: snapshot?.meta?.provenance || null,
      model: 'SIMULATED',
      detail: null,
      real_data: false,
    },
    has_memo: Boolean(snapshot?.memos?.[accountId]),
    actions: [],
  }
}

/** One account's timeline, in the API's `drishtiTimeline` shape. */
export function snapshotTimeline(snapshot, accountId) {
  return (snapshot?.timelines?.[accountId] || []).map((point) => ({
    date: point.date,
    pd: point.pd,
    pd_smooth: point.pd_smooth ?? point.pd,
    bucket: point.bucket,
    // The generator emits NaN for a channel this portfolio does not have; export_demo
    // turns it into null. Keep it null — `toSeries` is what decides how to draw a gap.
    utilisation: point.utilisation ?? null,
    inflow: point.inflow ?? null,
    dpd: point.dpd ?? null,
  }))
}

/** The drafted memo, in the API's `drishtiMemo` shape. */
export function snapshotMemo(snapshot, accountId) {
  const memo = snapshot?.memos?.[accountId]
  return {
    account_id: accountId,
    memo: memo || '',
    generated: Boolean(memo),
    disclaimer: 'Auto-drafted from model output and simulated bank data. Review every figure before this text leaves the bank.',
    human_review_required: true,
  }
}

/** `drishtiMetrics`, assembled from the snapshot's own blocks. */
export function snapshotMetrics(snapshot) {
  const summary = snapshot?.portfolio_summary || {}
  return {
    published: true,
    metrics: snapshot?.metrics || {},
    summary: {
      red: summary.red,
      amber: summary.amber,
      green: summary.green,
      red_thr: summary.red_thr,
      amber_thr: summary.amber_thr,
      total_accounts: summary.total_accounts ?? snapshot?.meta?.n_accounts_scored ?? (snapshot?.portfolio || []).length,
      exposure_at_risk: summary.exposure_at_risk,
    },
    ecosystem: snapshot?.ecosystem || null,
    rigor: snapshot?.rigor || null,
    real_data: null,
    generated_from: 'app/public/demo_data.json — the frozen snapshot bundled with this build.',
    provenance: snapshot?.meta?.provenance || null,
    source: 'snapshot',
    n_rows: (snapshot?.portfolio || []).length,
    thresholds: snapshotThresholds(snapshot),
  }
}

/** `drishtiValidation` has no snapshot equivalent — say so rather than invent one. */
export function snapshotValidation() {
  return {
    published: false,
    report: null,
    criteria_sha: null,
    verify_result: null,
    available: false,
    note: 'The validation report lives in the platform database and is attached to a published model run. This frozen bundle has no backend to read it from.',
  }
}
