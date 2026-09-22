// Borrower watch-list — all lending portfolios.
//
// The filters and the sort are the contract's allowlist, not free text: `portfolio`,
// `bucket`, `constitution`, `secured` and `sort ∈ {pd, sanctioned, dpd, runway_months,
// first_warning_lead}` are what `GET /drishti/portfolio` accepts, so anything the UI
// offers is something the server will actually honour. DPD band and ticket band are
// derived client-side from columns the payload already carries — they are labelled as
// such rather than sent as query parameters the API would ignore.
//
// A credit officer sees only their scoped portfolios. That scoping is the server's
// (`meta.scope` says what it applied); this screen states it so the officer knows the
// list is short because of their scope and not because the book is clean.

import { useCallback, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Info, Search } from 'lucide-react'
import AppShell from '../components/AppShell'
import AccountDetail from '../components/AccountDetail'
import Kpis from '../components/Kpis'
import DataTable, { SortableHeader, useRovingRows } from '../components/DataTable'
import SourceBadge from '../components/SourceBadge'
import Empty from '../components/states/Empty'
import ErrorState from '../components/states/ErrorState'
import Loading from '../components/states/Loading'
import { useAuth } from '../auth/AuthContext'
import useAsync from '../lib/useAsync'
import { inr, pct, RAG } from '../lib/format'
import { loadMetrics, loadWatchlist } from '../domain/drishti'
import { DPD_BANDS, TICKET_BANDS, dpdBand, ticketBand } from '../domain/shapes'
import { badgeForMode } from '../domain/provenance'

const PORTFOLIOS = ['MSME-CC', 'MSME-TL', 'Housing', 'Education', 'Agri', 'Retail-Unsecured', 'LAP', 'Auto']
const CONSTITUTIONS = ['Proprietorship', 'Partnership', 'PvtLtd', 'LLP', 'Individual']
const BUCKETS = [
  { key: '', label: 'All bands' },
  { key: 'red', label: 'Red — act now' },
  { key: 'amber', label: 'Amber — watch' },
  { key: 'green', label: 'Green — healthy' },
]
const SORTABLE = ['pd', 'sanctioned', 'dpd', 'runway_months', 'first_warning_lead']
const PAGE_SIZE = 50

function Select({ label, value, onChange, children, id }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">{label}</label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
      >
        {children}
      </select>
    </div>
  )
}

export default function Watchlist() {
  const { isStatic, scope, roleCode } = useAuth()
  const live = !isStatic
  const [params, setParams] = useSearchParams()

  const selected = params.get('account')
  const portfolio = params.get('portfolio') || ''
  const bucket = params.get('bucket') || ''
  const constitution = params.get('constitution') || ''
  const dpd = params.get('dpd') || ''
  const ticket = params.get('ticket') || ''
  const page = Math.max(0, Number(params.get('page') || 0))
  const sortKey = SORTABLE.includes(params.get('sort')) ? params.get('sort') : 'pd'
  const [q, setQ] = useState('')

  const patch = useCallback((changes, { resetPage = true } = {}) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [key, value] of Object.entries(changes)) {
        if (value === '' || value === null || value === undefined) next.delete(key)
        else next.set(key, String(value))
      }
      if (resetPage && !('page' in changes)) next.delete('page')
      return next
    }, { replace: true })
  }, [setParams])

  const query = useMemo(() => ({
    portfolio: portfolio || undefined,
    bucket: bucket || undefined,
    constitution: constitution || undefined,
    sort: sortKey,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }), [portfolio, bucket, constitution, sortKey, page])

  const listing = useAsync(
    ({ signal }) => loadWatchlist({ live, params: query, signal }),
    [live, JSON.stringify(query)],
  )
  // The band counts come from the published run's own roll-up, not from the page of rows
  // on screen — a KPI that changed when you paged would be a lie about the book.
  const overview = useAsync(({ signal }) => loadMetrics({ live, signal }), [live])

  const thresholds = listing.meta?.thresholds
  const rows = useMemo(() => {
    let out = listing.data || []
    if (dpd) out = out.filter((r) => dpdBand(r.dpd) === dpd)
    if (ticket) out = out.filter((r) => ticketBand(r.sanctioned) === ticket)
    if (q.trim()) {
      const needle = q.trim().toLowerCase()
      out = out.filter((r) =>
        r.account_id?.toLowerCase().includes(needle)
        || r.portfolio?.toLowerCase().includes(needle)
        || r.sector?.toLowerCase().includes(needle))
    }
    return out
  }, [listing.data, dpd, ticket, q])

  const open = useCallback((accountId) => patch({ account: accountId }, { resetPage: false }), [patch])
  const { bodyRef, rowProps } = useRovingRows(rows.length, { onActivate: open })

  const total = listing.meta?.total ?? rows.length
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const anyMoved = rows.some((r) => r.bucket_moved)
  // DPD, ticket band and the search box filter the page the server already sent. Saying
  // "showing 1–12 of 160" while three client filters are on would describe neither.
  const clientFiltered = rows.length !== (listing.data?.length ?? 0)
  const badge = badgeForMode(listing.meta?.provenance_mode, listing.source)
  const scopeNote = listing.meta?.scope

  return (
    <AppShell
      view="portfolio"
      title="Borrower Watch-list — all lending portfolios"
      subtitle={
        listing.meta?.reference_month
          ? `Predicting default 12 months ahead · book as of ${listing.meta.reference_month}`
          : 'Predicting default 12 months ahead'
      }
      help="watchlist"
      source={badge.source}
      sandbox={badge.sandbox}
      sourceDetail={badge.detail}
    >
      {Array.isArray(scopeNote) && scopeNote.length > 0 && (
        <div className="flex items-start gap-2 rounded-xl border border-idbi-green/30 bg-idbi-green/5 px-4 py-3 text-sm text-slate-700">
          <Info size={16} className="mt-0.5 shrink-0 text-idbi-green" aria-hidden="true" />
          <p>Showing only your portfolios: <b>{scopeNote.join(', ')}</b>.</p>
        </div>
      )}

      {listing.error ? (
        <ErrorState
          title="Could not load the watch-list"
          error={listing.error}
          onRetry={listing.reload}
        />
      ) : listing.loading && !listing.data ? (
        <Loading label="Loading the watch-list…" />
      ) : (
        <>
          {listing.meta?.bucket_source === 'live' && (
            <p className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs font-semibold leading-relaxed text-rag-ambertx">
              <Info size={14} className="shrink-0" aria-hidden="true" />
              Live re-band · threshold change in force — the bands below are recomputed against the thresholds a
              manager has moved since this run was published, not the run’s own published book.
            </p>
          )}

          {overview.data?.summary && <Kpis summary={overview.data.summary} metrics={overview.data.metrics} />}

          <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-end gap-3 border-b border-slate-200 p-3">
              <Select id="f-portfolio" label="Portfolio" value={portfolio} onChange={(v) => patch({ portfolio: v })}>
                <option value="">All portfolios</option>
                {(Array.isArray(scope) && scope.length && roleCode === 'CO' ? scope : PORTFOLIOS).map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </Select>
              <Select id="f-bucket" label="Band" value={bucket} onChange={(v) => patch({ bucket: v })}>
                {BUCKETS.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
              </Select>
              <Select id="f-constitution" label="Constitution" value={constitution} onChange={(v) => patch({ constitution: v })}>
                <option value="">All</option>
                {CONSTITUTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
              <Select id="f-dpd" label="DPD band" value={dpd} onChange={(v) => patch({ dpd: v })}>
                <option value="">All</option>
                {DPD_BANDS.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
              </Select>
              <Select id="f-ticket" label="Ticket band" value={ticket} onChange={(v) => patch({ ticket: v })}>
                <option value="">All</option>
                {TICKET_BANDS.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
              </Select>

              <div className="ml-auto flex flex-col gap-1">
                <label htmlFor="f-search" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                  Search this page
                </label>
                <div className="relative">
                  <Search size={15} className="pointer-events-none absolute left-2.5 top-2.5 text-slate-600" aria-hidden="true" />
                  <input
                    id="f-search"
                    type="search"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder="Account id, portfolio, sector"
                    className="w-56 rounded-lg border border-slate-300 py-1.5 pl-8 pr-3 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
                  />
                </div>
              </div>
            </div>

            {anyMoved && (
              <p className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs leading-relaxed text-rag-ambertx">
                <b>Band</b> is recomputed against the thresholds in force right now; <b>published</b> is the band the
                model run shipped with. They differ because a manager has moved a threshold since — the score itself
                has not been recomputed, and no score row was modified.
              </p>
            )}

            {rows.length === 0 ? (
              <div className="p-4">
                <Empty
                  title="No accounts match these filters"
                  hint={
                    total > 0
                      ? 'The book has accounts, but none in this combination. Widen the band or clear a filter.'
                      : 'This model run published no accounts you are scoped to see.'
                  }
                />
              </div>
            ) : (
              <>
                <div className="max-h-[560px] overflow-auto scroll-thin">
                  <DataTable caption={`Watch-list, ${rows.length} of ${total} accounts, sorted by ${sortKey}`}>
                    <thead className="sticky top-0 z-10 bg-slate-50 text-xs">
                      <tr>
                        <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Account</th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Portfolio</th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Band</th>
                        <SortableHeader column="pd" sort={{ key: sortKey, direction: 'desc' }} onSort={(s) => patch({ sort: s.key })} align="right">
                          PD (12-mo)
                        </SortableHeader>
                        <SortableHeader column="dpd" sort={{ key: sortKey, direction: 'desc' }} onSort={(s) => patch({ sort: s.key })} align="right">
                          DPD
                        </SortableHeader>
                        <SortableHeader column="first_warning_lead" sort={{ key: sortKey, direction: 'desc' }} onSort={(s) => patch({ sort: s.key })} align="right">
                          Lead
                        </SortableHeader>
                        <SortableHeader column="runway_months" sort={{ key: sortKey, direction: 'desc' }} onSort={(s) => patch({ sort: s.key })} align="right" title="Projected months before the risk trend crosses the next threshold (median error ≈3 months)">
                          Runway
                        </SortableHeader>
                        <SortableHeader column="sanctioned" sort={{ key: sortKey, direction: 'desc' }} onSort={(s) => patch({ sort: s.key })} align="right">
                          Exposure
                        </SortableHeader>
                        <th scope="col" className="px-3 py-2 text-left font-semibold text-slate-600">Top early-warning signal</th>
                      </tr>
                    </thead>
                    <tbody ref={bodyRef}>
                      {rows.map((r, index) => {
                        const rag = RAG[r.bucket] || RAG.green
                        return (
                          <tr
                            key={r.account_id}
                            {...rowProps(index, r.account_id)}
                            onClick={() => open(r.account_id)}
                            aria-label={`${r.account_id}, ${rag.label} band, PD ${pct(r.pd)}`}
                            className="cursor-pointer border-t border-slate-100 hover:bg-idbi-green/5 focus:bg-idbi-green/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-idbi-green"
                          >
                            <th scope="row" className="px-3 py-2.5 text-left font-semibold text-slate-800">
                              <span className={`mr-2 inline-block h-2 w-2 rounded-full ${rag.dot}`} aria-hidden="true" />
                              {r.account_id}
                            </th>
                            <td className="px-3 py-2.5 text-slate-600">{r.portfolio || '—'}</td>
                            <td className="px-3 py-2.5">
                              <span className={`rounded-full border px-2 py-0.5 text-[11px] font-bold ${rag.soft}`}>{rag.label}</span>
                              {r.bucket_moved && (
                                <span className="ml-1.5 text-[11px] text-slate-600">
                                  published <b>{r.published_bucket}</b>
                                </span>
                              )}
                            </td>
                            <td className={`px-3 py-2.5 text-right font-bold ${rag.text}`}>{pct(r.pd)}</td>
                            <td className="px-3 py-2.5 text-right text-slate-600">{r.dpd === null ? '—' : Math.round(r.dpd)}</td>
                            <td className="px-3 py-2.5 text-right text-slate-600">{r.first_warning_lead ? `${r.first_warning_lead} mo` : '—'}</td>
                            <td className={`px-3 py-2.5 text-right ${r.runway_months !== null && r.runway_months <= 3 ? 'font-semibold text-rag-redtx' : 'text-slate-600'}`}>
                              {r.runway_months === null ? '—' : `≈${Math.round(r.runway_months)} mo`}
                            </td>
                            <td className="px-3 py-2.5 text-right text-slate-600">{inr(r.sanctioned)}</td>
                            <td className="max-w-[280px] truncate px-3 py-2.5 text-slate-600">{r.reasons?.[0] || '—'}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </DataTable>
                </div>

                <div className="flex flex-wrap items-center gap-3 border-t border-slate-200 px-3 py-2.5 text-sm">
                  <p className="text-slate-600" role="status" aria-live="polite">
                    {clientFiltered
                      ? <>Showing <b>{rows.length}</b> of the {listing.data.length} accounts on this page that match the
                        DPD, ticket-band and search filters — {total.toLocaleString('en-IN')} accounts in the book.</>
                      : <>Showing {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + rows.length} of {total.toLocaleString('en-IN')}</>}
                    {thresholds && (
                      <> · Red ≥ {pct(thresholds.red_thr, 1)}, Amber ≥ {pct(thresholds.amber_thr, 1)}</>
                    )}
                  </p>
                  <div className="ml-auto flex items-center gap-1">
                    <button
                      type="button"
                      disabled={page === 0}
                      onClick={() => patch({ page: page - 1 }, { resetPage: false })}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green disabled:opacity-40"
                    >
                      <ChevronLeft size={14} aria-hidden="true" /> Previous
                    </button>
                    <span className="px-2 text-xs text-slate-600">Page {page + 1} of {pages}</span>
                    <button
                      type="button"
                      disabled={page + 1 >= pages}
                      onClick={() => patch({ page: page + 1 }, { resetPage: false })}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green disabled:opacity-40"
                    >
                      Next <ChevronRight size={14} aria-hidden="true" />
                    </button>
                  </div>
                </div>
              </>
            )}
          </section>

          <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <SourceBadge source={badge.source} sandbox={badge.sandbox} detail={badge.detail} iconOnly />
            Every figure on this screen comes from {listing.meta?.model_run_id
              ? <>published model run <code className="rounded bg-slate-100 px-1 font-mono text-[11px]">{listing.meta.model_run_id}</code></>
              : 'the bundled snapshot'}.
            {' '}
            <Link to="/data-sources" className="font-semibold text-idbi-green underline underline-offset-2">
              See which bank APIs were called
            </Link>
          </p>
        </>
      )}

      {selected && (
        <AccountDetail
          accountId={selected}
          live={live}
          thresholds={thresholds}
          onClose={() => patch({ account: '' }, { resetPage: false })}
        />
      )}
    </AppShell>
  )
}
