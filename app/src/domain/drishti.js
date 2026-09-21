// Every DRISHTi read and write, in one place.
//
// Each loader takes `{ live, signal, … }` and returns `{ data, meta, source }`:
//
//   live: true   -> the platform API, `contracts/openapi.json` `x-response-shapes`
//   live: false  -> the bundled snapshot, adapted to the same shape in `snapshot.js`
//
// `source` is what the SourceBadge on the screen reports, so a jury can always tell which
// of the two they are looking at. A screen never branches on the mode itself.
//
// Writes (memo, action, threshold, the admin operations) exist only in live mode: there is
// nothing to write to in a frozen bundle, and pretending otherwise would fake an audit
// trail. They throw `StaticModeError`, which the screens render as a disabled control.

import { apiFetch } from '../lib/api'
import { toRow } from './shapes'
import {
  loadRealModel, loadSnapshot, snapshotAccount, snapshotMemo, snapshotMetrics,
  snapshotThresholds, snapshotTimeline, snapshotValidation,
} from './snapshot'

export const SOURCE_KIND = { API: 'api', SNAPSHOT: 'snapshot' }

export class StaticModeError extends Error {
  constructor(what = 'This action') {
    super(`${what} needs the live platform. This is the frozen demo bundle, which has no backend to record it against.`)
    this.name = 'StaticModeError'
    this.isStatic = true
  }
}

/** Query string from a filter object, dropping empties so the URL stays readable. */
export function query(params = {}) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === 'all') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

// --------------------------------------------------------------------------- watch-list

/**
 * The watch-list. The API filters and paginates server-side against its allowlist; the
 * snapshot path applies the same filters client-side so the two screens behave alike.
 *
 * @param {object} opts
 * @param {boolean} opts.live
 * @param {object} opts.params  portfolio, bucket, constitution, secured, sort, limit, offset
 */
export async function loadWatchlist({ live, params = {}, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch(`/drishti/portfolio${query(params)}`, { signal })
    const thresholds = meta?.thresholds
    return {
      data: (data || []).map((row) => toRow(row, { thresholds })),
      meta: meta || {},
      source: SOURCE_KIND.API,
    }
  }

  const snapshot = await loadSnapshot(signal)
  const thresholds = snapshotThresholds(snapshot)
  let rows = (snapshot.portfolio || []).map((row) => toRow(row, { thresholds }))
  if (params.portfolio) rows = rows.filter((r) => r.portfolio === params.portfolio)
  if (params.bucket) rows = rows.filter((r) => r.bucket === params.bucket)
  if (params.constitution) rows = rows.filter((r) => r.constitution === params.constitution)
  if (params.secured !== undefined && params.secured !== '') {
    const want = params.secured === true || params.secured === 'true'
    rows = rows.filter((r) => Boolean(r.secured) === want)
  }
  if (params.sort) {
    const key = params.sort
    rows = [...rows].sort((a, b) => (b[key] ?? -Infinity) - (a[key] ?? -Infinity))
  }
  const total = rows.length
  const offset = Number(params.offset) || 0
  const limit = Number(params.limit) || 50
  return {
    data: rows.slice(offset, offset + limit),
    meta: {
      total,
      limit,
      offset,
      thresholds,
      scope: 'all',
      provenance_mode: 'snapshot',
      generated_at: snapshot.meta?.generated_at || null,
      reference_month: snapshot.meta?.reference_month || null,
      n_accounts_scored: snapshot.meta?.n_accounts_scored ?? total,
    },
    source: SOURCE_KIND.SNAPSHOT,
  }
}

/** Every row, for the client-side exhibits (portfolio risk) that group the whole book. */
export async function loadWholeBook({ live, signal } = {}) {
  if (!live) {
    const snapshot = await loadSnapshot(signal)
    const thresholds = snapshotThresholds(snapshot)
    return {
      data: (snapshot.portfolio || []).map((row) => toRow(row, { thresholds })),
      meta: { total: (snapshot.portfolio || []).length, thresholds, scope: 'all', ecosystem: snapshot.ecosystem },
      source: SOURCE_KIND.SNAPSHOT,
    }
  }
  // 500 is the contract's maximum page. Page until the server says there is no more, and
  // say so in the meta when a cap stops us short — an exhibit computed over part of the
  // book, presented as the whole book, is the kind of quiet lie this product exists to
  // avoid.
  const PAGE = 500
  const MAX_PAGES = 40 // 20,000 accounts; beyond that the exhibits belong server-side
  const rows = []
  let meta = {}
  let truncated = false
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await apiFetch(`/drishti/portfolio${query({ limit: PAGE, offset: page * PAGE })}`, { signal })
    meta = result.meta || {}
    const batch = result.data || []
    rows.push(...batch.map((row) => toRow(row, { thresholds: meta.thresholds })))
    if (batch.length < PAGE) break
    if (rows.length >= (meta.total ?? rows.length)) break
    if (page === MAX_PAGES - 1) truncated = true
  }
  return {
    data: rows,
    meta: { ...meta, loaded: rows.length, truncated },
    source: SOURCE_KIND.API,
  }
}

// ------------------------------------------------------------------------ account detail

export async function loadAccount({ live, id, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch(`/drishti/account/${encodeURIComponent(id)}`, { signal })
    return { data, meta: meta || {}, source: SOURCE_KIND.API }
  }
  const snapshot = await loadSnapshot(signal)
  const account = snapshotAccount(snapshot, id)
  if (!account) {
    const error = new Error(`Account ${id} is not in this snapshot.`)
    error.status = 404
    throw error
  }
  return { data: account, meta: { provenance_mode: 'snapshot' }, source: SOURCE_KIND.SNAPSHOT }
}

export async function loadTimeline({ live, id, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch(`/drishti/account/${encodeURIComponent(id)}/timeline`, { signal })
    return { data: data || [], meta: meta || {}, source: SOURCE_KIND.API }
  }
  const snapshot = await loadSnapshot(signal)
  return {
    data: snapshotTimeline(snapshot, id),
    meta: { thresholds: snapshotThresholds(snapshot), reference_month: snapshot.meta?.reference_month },
    source: SOURCE_KIND.SNAPSHOT,
  }
}

export async function loadMemo({ live, id, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch(`/drishti/account/${encodeURIComponent(id)}/memo`, { signal })
    return { data, meta: meta || {}, source: SOURCE_KIND.API }
  }
  const snapshot = await loadSnapshot(signal)
  return { data: snapshotMemo(snapshot, id), meta: {}, source: SOURCE_KIND.SNAPSHOT }
}

export async function saveMemo({ live, id, memo, signal } = {}) {
  if (!live) throw new StaticModeError('Saving a memo')
  const { data } = await apiFetch(`/drishti/account/${encodeURIComponent(id)}/memo`, {
    method: 'PUT', body: { memo }, signal,
  })
  return data
}

/** The action enum, straight out of `contracts/openapi.json` `drishtiAction`. */
export const ACTIONS = [
  { value: 'acknowledged', label: 'Acknowledged', hint: 'Seen and triaged; no contact yet.' },
  { value: 'contacted_borrower', label: 'Contacted borrower', hint: 'Spoke to the borrower about the flag.' },
  { value: 'site_visit', label: 'Site visit', hint: 'Visited the business premises.' },
  { value: 'restructure_proposed', label: 'Restructure proposed', hint: 'A restructuring has been put to the borrower.' },
  { value: 'escalated', label: 'Escalated', hint: 'Referred upward for a decision.' },
  // What the OFFICER did, recorded after the fact. The model never assigns a
  // regulatory classification — its Red band says an account resembles the ones
  // that went bad, which is not the same statement as "31-60 days overdue".
  { value: 'classified_sma1', label: 'Classified SMA-1', hint: 'The officer classified the account as SMA-1 in the CBS. The model does not assign this.' },
  { value: 'false_positive', label: 'False positive', hint: 'The flag does not reflect the account. Recorded for model review.' },
  { value: 'closed', label: 'Closed', hint: 'No further action needed on this flag.' },
]

export async function recordAction({ live, id, action, note, signal } = {}) {
  if (!live) throw new StaticModeError('Recording an action')
  const { data } = await apiFetch(`/drishti/account/${encodeURIComponent(id)}/action`, {
    method: 'POST', body: note ? { action, note } : { action }, signal,
  })
  return data
}

// ---------------------------------------------------------------------- model & metrics

export async function loadMetrics({ live, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch('/drishti/metrics', { signal })
    return { data, meta: meta || {}, source: SOURCE_KIND.API }
  }
  const snapshot = await loadSnapshot(signal)
  return {
    data: snapshotMetrics(snapshot),
    meta: { provenance_mode: 'snapshot', reference_month: snapshot.meta?.reference_month },
    source: SOURCE_KIND.SNAPSHOT,
  }
}

export async function loadValidation({ live, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch('/drishti/validation', { signal })
    return { data, meta: meta || {}, source: SOURCE_KIND.API }
  }
  return { data: snapshotValidation(), meta: {}, source: SOURCE_KIND.SNAPSHOT }
}

export async function loadRealDataModel({ live: _live, signal } = {}) {
  return { data: await loadRealModel(signal), meta: {}, source: SOURCE_KIND.SNAPSHOT }
}

// ---------------------------------------------------------------------------- thresholds

export async function loadThreshold({ live, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch('/drishti/threshold', { signal })
    return { data, meta: meta || {}, source: SOURCE_KIND.API }
  }
  const snapshot = await loadSnapshot(signal)
  return { data: snapshotThresholds(snapshot), meta: {}, source: SOURCE_KIND.SNAPSHOT }
}

export async function saveThreshold({ live, red_thr: red, amber_thr: amber, justification, signal } = {}) {
  if (!live) throw new StaticModeError('Changing a threshold')
  const { data } = await apiFetch('/drishti/threshold', {
    method: 'PUT',
    body: { red_thr: red, amber_thr: amber, justification },
    signal,
  })
  return data
}

// --------------------------------------------------------------------- data sources

export async function loadSync({ live, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch('/meta/sync', { signal })
    return { data: data || [], meta: meta || {}, source: SOURCE_KIND.API }
  }
  return {
    data: [],
    meta: { total: 0, runs: {}, real_data: false, live_apis: [], gateway: null, offline: true },
    source: SOURCE_KIND.SNAPSHOT,
  }
}

export async function loadProvenance({ live, signal } = {}) {
  if (live) {
    const { data, meta } = await apiFetch('/meta/provenance', { signal })
    return { data, meta: meta || {}, source: SOURCE_KIND.API }
  }
  const snapshot = await loadSnapshot(signal)
  return {
    data: {
      real_data: false,
      live_apis: [],
      live_records: 0,
      products: {
        drishti: {
          model_run_id: null,
          provenance_mode: 'snapshot',
          generated_from: 'app/public/demo_data.json',
          families: snapshot.meta?.provenance || null,
          status: 'frozen_bundle',
        },
      },
      note: 'This build has no backend. Every family below is what the bundled snapshot recorded when it was written.',
    },
    meta: {},
    source: SOURCE_KIND.SNAPSHOT,
  }
}

// --------------------------------------------------------------------------------- admin

export async function loadUsers({ signal } = {}) {
  const { data, meta } = await apiFetch('/admin/users', { signal })
  return { data: data || [], meta: meta || {} }
}

export async function createUser({ signal, ...body } = {}) {
  const { data } = await apiFetch('/admin/users', { method: 'POST', body, signal })
  return data
}

export async function setUserRole({ userId, role, scope, signal } = {}) {
  const body = scope?.length ? { role, scope } : { role }
  const { data } = await apiFetch(`/admin/users/${userId}/role`, { method: 'POST', body, signal })
  return data
}

export async function setUserActive({ userId, active, signal } = {}) {
  const path = `/admin/users/${userId}/${active ? 'activate' : 'deactivate'}`
  const { data } = await apiFetch(path, { method: 'POST', signal })
  return data
}

export async function resetUserPassword({ userId, signal } = {}) {
  const { data } = await apiFetch(`/admin/users/${userId}/reset-password`, { method: 'POST', signal })
  return data
}

export async function loadAudit({ params = {}, signal } = {}) {
  const { data, meta } = await apiFetch(`/admin/audit${query(params)}`, { signal })
  return { data: data || [], meta: meta || {} }
}

export async function verifyAuditChain({ signal } = {}) {
  const { data } = await apiFetch('/admin/audit/verify', { method: 'POST', signal })
  return data
}
