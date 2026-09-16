// One account's whole story: score over time, the evidence under it, what the bank has
// actually observed about this borrower, the drafted memo, and the officer's own record.
//
// The bug this file used to carry, and the reason the channel strip exists:
//
//     util: +(p.utilisation * 100).toFixed(0)
//
// `null * 100` is `0`, so a housing borrower — who has no credit limit and therefore no
// utilisation — was drawn as a flat 0% line. The chart said "this borrower uses none of
// their limit"; the truth was "this product has no limit". `renderField` and the channel
// strip make that distinction visible instead of silently flattening it.

import { useCallback, useMemo, useRef, useState } from 'react'
import {
  Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import {
  CalendarClock, Check, CircleSlash, Copy, FileText, Pencil, Share2, TriangleAlert,
} from 'lucide-react'
import Dialog from './Dialog'
import SourceBadge from './SourceBadge'
import Empty from './states/Empty'
import ErrorState from './states/ErrorState'
import Loading from './states/Loading'
import { useToast } from './Toasts'
import useAsync from '../lib/useAsync'
import { inr, pct, RAG } from '../lib/format'
import { ACTIONS, loadAccount, loadMemo, loadTimeline, recordAction, saveMemo } from '../domain/drishti'
import { FIELD_STATE, normaliseChannels, renderField } from '../domain/channels'
import { badgeForFamilySource } from '../domain/provenance'

/** The timeline, with absent channels kept absent. Recharts draws a gap for `null`. */
export function toSeries(points, channels) {
  if (!points?.length) return []
  const firstInflow = points.find((p) => p.inflow != null)?.inflow || null
  return points.map((p) => {
    const util = renderField(p.utilisation, 'utilisation', channels)
    return {
      date: p.date,
      pd: p.pd == null ? null : +((p.pd_smooth ?? p.pd) * 100).toFixed(1),
      pdRaw: p.pd == null ? null : +(p.pd * 100).toFixed(1),
      // null, never 0: a portfolio without a credit limit has no utilisation to draw.
      util: util.state === FIELD_STATE.OBSERVED ? +(p.utilisation * 100).toFixed(0) : null,
      inflowIdx: p.inflow == null || !firstInflow ? null : +((p.inflow / firstInflow) * 100).toFixed(0),
      dpd: p.dpd ?? null,
      bucket: p.bucket,
    }
  })
}

function ChannelStrip({ channels }) {
  const rows = normaliseChannels(channels)
  if (rows.length === 0) return null
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-bold text-slate-800">What the bank can actually see about this borrower</h3>
      <p className="mb-3 mt-1 text-xs leading-relaxed text-slate-600">
        Each product carries a different set of observation channels. A channel that is not listed here has no
        data for this account — not a value of zero — and every figure drawn from it reads “not applicable”.
      </p>
      <ul className="flex flex-wrap gap-2">
        {rows.map((c) => {
          const badge = badgeForFamilySource(c.source)
          return (
            <li
              key={c.channel}
              className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${
                c.present ? 'border-slate-200 bg-slate-50 text-slate-700' : 'border-slate-200 bg-white text-slate-500'
              }`}
            >
              {c.present
                ? <Check size={13} className="text-idbi-green" aria-hidden="true" />
                : <CircleSlash size={13} className="text-slate-500" aria-hidden="true" />}
              <span className="font-semibold">{c.label}</span>
              <span className="sr-only">{c.present ? 'observed' : 'not collected'}</span>
              {c.source && <SourceBadge source={badge.source} sandbox={badge.sandbox} iconOnly className="ml-0.5" />}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function ActionRecorder({ accountId, live, onRecorded }) {
  const toast = useToast()
  const [action, setAction] = useState(ACTIONS[0].value)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const chosen = ACTIONS.find((a) => a.value === action)

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const recorded = await recordAction({ live, id: accountId, action, note: note.trim() || undefined })
      toast.audited(
        `“${chosen.label}” recorded against ${accountId}.`,
        recorded?.actor_ein ? `Actor ${recorded.actor_ein}, ${new Date(recorded.at).toLocaleString('en-IN')}.` : undefined,
      )
      setNote('')
      onRecorded?.(recorded)
    } catch (err) {
      setError(err)
      toast.error('Could not record that action.', err?.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-bold text-slate-800">Record what you did</h3>
      <p className="mb-3 mt-1 text-xs leading-relaxed text-slate-600">
        Every entry is written to the append-only, hash-chained audit log with your user id and cannot be edited or
        deleted afterwards. Nothing here changes the customer’s facility.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="action-kind" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Action</label>
          <select
            id="action-kind"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="rounded-lg border border-slate-300 px-2.5 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
          >
            {ACTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
          <p className="text-xs text-slate-600">{chosen?.hint}</p>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="action-note" className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
            Note <span className="font-normal normal-case text-slate-500">(optional, up to 2,000 characters)</span>
          </label>
          <textarea
            id="action-note"
            value={note}
            maxLength={2000}
            rows={3}
            onChange={(e) => setNote(e.target.value)}
            className="rounded-lg border border-slate-300 px-2.5 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
          />
        </div>
        {error && <p className="text-xs text-rag-redtx" role="alert">{error.message}</p>}
        <button
          type="submit"
          disabled={busy || !live}
          className="rounded-lg bg-idbi-green px-4 py-2 text-sm font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2 disabled:opacity-50"
        >
          {busy ? 'Recording…' : 'Record action'}
        </button>
        {!live && (
          <p className="text-xs text-slate-600">
            This is the frozen demo bundle. There is no audit log to write to, so the control is disabled rather
            than pretending to record something.
          </p>
        )}
      </form>
    </section>
  )
}

function Memo({ accountId, live }) {
  const toast = useToast()
  const memo = useAsync(({ signal }) => loadMemo({ live, id: accountId, signal }), [live, accountId])
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const textareaRef = useRef(null)

  const text = memo.data?.memo || ''

  const startEdit = () => { setDraft(text); setEditing(true) }
  const save = async () => {
    setBusy(true)
    try {
      await saveMemo({ live, id: accountId, memo: draft })
      toast.audited(`Memo for ${accountId} saved.`, 'The previous version is retained; the change is in the audit log.')
      setEditing(false)
      memo.reload()
    } catch (err) {
      toast.error('Could not save the memo.', err?.message)
    } finally {
      setBusy(false)
    }
  }

  const copy = () => {
    navigator.clipboard?.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (memo.loading) return <Loading label="Loading the memo…" />
  if (memo.error) return <ErrorState title="Could not load the memo" error={memo.error} onRetry={memo.reload} />
  if (!text && !editing) {
    return (
      <Empty
        icon={FileText}
        title="No memo yet"
        hint="A memo is drafted from the model output when this account is flagged. You can also write one."
        action={live ? (
          <button
            type="button"
            onClick={startEdit}
            className="rounded-lg bg-idbi-green px-3 py-1.5 text-sm font-semibold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2"
          >
            Write a memo
          </button>
        ) : null}
      />
    )
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <FileText size={16} className="text-idbi-green" aria-hidden="true" />
        <h3 className="flex-1 text-sm font-bold text-slate-800">
          {memo.data?.generated ? 'Auto-drafted early-warning memo' : 'Early-warning memo'}
        </h3>
        {!editing && (
          <>
            <button
              type="button"
              onClick={copy}
              className="flex items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-600 transition hover:text-idbi-green focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
            >
              {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            {live && (
              <button
                type="button"
                onClick={startEdit}
                className="flex items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-600 transition hover:text-idbi-green focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
              >
                <Pencil size={13} aria-hidden="true" /> Edit
              </button>
            )}
          </>
        )}
      </div>

      {editing ? (
        <div className="space-y-2">
          <label htmlFor="memo-draft" className="sr-only">Memo text</label>
          <textarea
            id="memo-draft"
            ref={textareaRef}
            value={draft}
            maxLength={8000}
            rows={10}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full rounded-lg border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={save}
              disabled={busy || !draft.trim()}
              className="rounded-lg bg-idbi-green px-3 py-1.5 text-sm font-semibold text-white transition hover:bg-idbi-greendk focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green focus-visible:ring-offset-2 disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save memo'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <pre className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-relaxed text-slate-700">
          {text}
        </pre>
      )}

      {memo.data?.disclaimer && (
        <p className="mt-3 border-t border-slate-200 pt-3 text-xs leading-relaxed text-slate-600">
          {memo.data.human_review_required && <b>Review before use. </b>}
          {memo.data.disclaimer}
        </p>
      )}
    </section>
  )
}

export default function AccountDetail({ accountId, live = true, thresholds: fallbackThresholds, onClose }) {
  const account = useAsync(({ signal }) => loadAccount({ live, id: accountId, signal }), [live, accountId], { enabled: Boolean(accountId) })
  const timeline = useAsync(({ signal }) => loadTimeline({ live, id: accountId, signal }), [live, accountId], { enabled: Boolean(accountId) })
  const [actionCount, setActionCount] = useState(0)

  const rec = account.data
  const channels = rec?.channels_present
  const scores = rec?.scores || {}
  const thresholds = rec?.thresholds || fallbackThresholds || {}
  const rag = RAG[scores.bucket] || RAG.green
  const series = useMemo(() => toSeries(timeline.data, channels), [timeline.data, channels])
  const refMonth = timeline.meta?.reference_month || null
  const utilState = renderField(rec?.utilisation, 'utilisation', channels)
  const hasUtil = series.some((p) => p.util !== null)
  const hasInflow = series.some((p) => p.inflowIdx !== null)
  const lastDate = series[series.length - 1]?.date
  const futureMonths = refMonth ? series.filter((p) => p.date > refMonth).length : 0
  const hasFuture = futureMonths >= 2

  const onRecorded = useCallback(() => setActionCount((n) => n + 1), [])

  return (
    <Dialog
      open={Boolean(accountId)}
      onClose={onClose}
      variant="drawer"
      testId="account-detail"
      title={rec ? `${rec.account_id} — ${rag.label} band` : `Account ${accountId}`}
      description={rec
        ? [rec.portfolio, rec.constitution, rec.sector, rec.region, rec.sanctioned && `${inr(Number(rec.sanctioned))} sanctioned`]
          .filter(Boolean).join(' · ')
        : undefined}
      closeLabel="Close account detail"
    >
      {account.loading ? (
        <Loading label={`Loading ${accountId}…`} />
      ) : account.error ? (
        <ErrorState
          title={account.error.status === 404 ? 'That account is not in this model run' : 'Could not load the account'}
          error={account.error}
          onRetry={account.reload}
        />
      ) : (
        <div className="space-y-5">
          {/* headline */}
          <div className="flex flex-wrap items-start gap-3">
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <div className={`text-3xl font-extrabold leading-none ${rag.text}`}>{pct(scores.pd)}</div>
              <div className="mt-1 text-[11px] uppercase tracking-wide text-slate-600">12-month default probability</div>
            </div>
            <div className="min-w-0 flex-1 space-y-2">
              {scores.published_bucket && scores.published_bucket !== scores.bucket && (
                <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-rag-ambertx">
                  Band is <b>{scores.bucket}</b> under the thresholds in force; the model run published
                  <b> {scores.published_bucket}</b>. A manager has moved a threshold since — the score is unchanged.
                </p>
              )}
              {scores.bucket === 'green' ? (
                <p className="inline-flex items-center gap-2 rounded-lg bg-idbi-green/10 px-3 py-2 text-sm font-semibold text-idbi-green">
                  <CalendarClock size={16} aria-hidden="true" /> Healthy — no early-warning flag
                </p>
              ) : (
                <p className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${rag.soft}`}>
                  <CalendarClock size={16} aria-hidden="true" /> On the watch-list · {rag.label}
                  {scores.first_warning_lead ? ` · first flagged ${scores.first_warning_lead} mo before trouble` : ''}
                </p>
              )}
              {rec.eco_red >= 1 && (
                <p className="inline-flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-sm font-semibold text-idbi-orangetx">
                  <Share2 size={16} aria-hidden="true" /> Ecosystem: {rec.eco_flagged} of {rec.eco_partners} trading partners flagged ({rec.eco_red} red)
                </p>
              )}
            </div>
          </div>

          {/* key figures, with absence stated */}
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'Outstanding', value: rec.outstanding == null ? '—' : inr(Number(rec.outstanding)) },
              { label: 'Days past due', value: rec.dpd == null ? '—' : String(Math.round(rec.dpd)) },
              {
                label: 'Credit-limit use',
                value: utilState.text,
                muted: utilState.state !== FIELD_STATE.OBSERVED,
                hint: utilState.state === FIELD_STATE.NOT_APPLICABLE
                  ? 'This product has no drawable limit, so there is no utilisation to report.'
                  : undefined,
              },
              { label: 'Runway', value: scores.runway_months == null ? '—' : `≈${Math.round(scores.runway_months)} mo` },
            ].map((item) => (
              <div key={item.label} className="rounded-xl border border-slate-200 bg-white p-3">
                <dt className="text-[11px] uppercase tracking-wide text-slate-600">{item.label}</dt>
                <dd className={`mt-0.5 text-lg font-extrabold ${item.muted ? 'text-sm font-semibold text-slate-500' : 'text-slate-900'}`}>
                  {item.value}
                </dd>
                {item.hint && <p className="mt-1 text-[11px] leading-relaxed text-slate-600">{item.hint}</p>}
              </div>
            ))}
          </dl>

          {/* score over time */}
          {timeline.loading ? (
            <Loading label="Loading the trajectory…" />
          ) : timeline.error ? (
            <ErrorState title="Could not load the trajectory" error={timeline.error} onRetry={timeline.reload} />
          ) : series.length === 0 ? (
            <Empty title="No month-by-month trajectory" hint="This model run published a single snapshot for the account, with no history behind it." />
          ) : (
            <>
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="mb-1 text-sm font-bold text-slate-800">Model risk score over time</h3>
                <p className="mb-3 text-xs leading-relaxed text-slate-600">
                  Both lines are the <b>model’s</b> 12-month default-risk score (green = smoothed, the value officers
                  act on; grey = raw monthly, shown for transparency) — <i>not</i> actual outcomes.
                </p>
                <ResponsiveContainer width="100%" height={235}>
                  <ComposedChart data={series} margin={{ top: 22, right: 8, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="pdFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#02684F" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#02684F" stopOpacity={0.03} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} interval="preserveStartEnd" minTickGap={24} />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#64748b' }} unit="%" />
                    <Tooltip formatter={(v, n) => [`${v}%`, n]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {hasFuture && (
                      <ReferenceArea x1={refMonth} x2={lastDate} fill="#0f172a" fillOpacity={0.07}
                        label={{ value: 'after today →', fontSize: 10, fill: '#475569', position: 'insideTopRight' }} />
                    )}
                    {thresholds.red_thr != null && (
                      <ReferenceLine y={thresholds.red_thr * 100} stroke="#b91c1c" strokeDasharray="4 4"
                        label={{ value: 'Red', fontSize: 9, fill: '#b91c1c', position: 'insideRight' }} />
                    )}
                    {thresholds.amber_thr != null && (
                      <ReferenceLine y={thresholds.amber_thr * 100} stroke="#b45309" strokeDasharray="4 4"
                        label={{ value: 'Amber', fontSize: 9, fill: '#b45309', position: 'insideRight' }} />
                    )}
                    {refMonth && (
                      <ReferenceLine x={refMonth} stroke="#0f172a" strokeWidth={2}
                        label={{ value: `TODAY · ${refMonth}`, fontSize: 11, fontWeight: 700, fill: '#0f172a', position: hasFuture ? 'top' : 'insideTopLeft' }} />
                    )}
                    <Area type="monotone" dataKey="pd" name="Risk score (smoothed)" stroke="#02684F" strokeWidth={2.5} fill="url(#pdFill)" isAnimationActive={false} connectNulls={false} />
                    <Line type="monotone" dataKey="pdRaw" name="Raw monthly score" stroke="#94a3b8" strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </section>

              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="mb-1 text-sm font-bold text-slate-800">The evidence underneath</h3>
                <p className="mb-3 text-xs leading-relaxed text-slate-600">
                  Cash inflows (indexed to 100 at the start of the window) against credit-limit use — the leading
                  signals, well before any missed payment.
                  {!hasUtil && (
                    <> <b>Credit-limit use is not plotted: this product has no drawable limit,</b> so there is no
                    utilisation to show — the line is absent rather than drawn at zero.</>
                  )}
                  {!hasInflow && <> <b>Inflows are not plotted for this account.</b></>}
                </p>
                {!hasUtil && !hasInflow ? (
                  <Empty title="Neither channel is available for this product" hint="Nothing has been inferred in their place." />
                ) : (
                  <ResponsiveContainer width="100%" height={200}>
                    <ComposedChart data={series} margin={{ top: 5, right: 8, left: -18, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} interval="preserveStartEnd" minTickGap={24} />
                      <YAxis yAxisId="l" tick={{ fontSize: 10, fill: '#64748b' }} />
                      <YAxis yAxisId="r" orientation="right" domain={[0, 110]} tick={{ fontSize: 10, fill: '#64748b' }} unit="%" />
                      <Tooltip />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      {refMonth && <ReferenceLine x={refMonth} yAxisId="l" stroke="#0f172a" strokeDasharray="5 3" />}
                      {hasInflow && (
                        <Line yAxisId="l" type="monotone" dataKey="inflowIdx" name="Bank inflows (index)" stroke="#0369a1" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
                      )}
                      {hasUtil && (
                        <Line yAxisId="r" type="monotone" dataKey="util" name="Credit-limit use %" stroke="#c2410c" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
                      )}
                    </ComposedChart>
                  </ResponsiveContainer>
                )}
              </section>
            </>
          )}

          <ChannelStrip channels={channels} />

          {/* reason codes */}
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h3 className="mb-3 text-sm font-bold text-slate-800">Why the model flagged this account</h3>
            <ul className="space-y-2">
              {(scores.reasons?.length ? scores.reasons : ['No elevated risk signals — account conduct is healthy.']).map((reason) => (
                <li key={reason} className="flex items-center gap-2.5 text-sm">
                  <span className={`grid h-6 w-6 place-items-center rounded-md ${scores.bucket === 'green' ? 'bg-green-50 text-rag-greentx' : 'bg-amber-50 text-rag-ambertx'}`}>
                    <TriangleAlert size={14} aria-hidden="true" />
                  </span>
                  <span className="text-slate-700">{reason}</span>
                </li>
              ))}
            </ul>
          </section>

          <Memo key={`memo-${accountId}`} accountId={accountId} live={live} />
          <ActionRecorder accountId={accountId} live={live} onRecorded={onRecorded} />

          {(rec.actions?.length > 0 || actionCount > 0) && (
            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="mb-2 text-sm font-bold text-slate-800">Actions recorded on this account</h3>
              <ul className="space-y-1.5 text-sm text-slate-700">
                {(rec.actions || []).map((a) => (
                  <li key={a.id} className="flex flex-wrap gap-2">
                    <b>{ACTIONS.find((x) => x.value === a.action)?.label || a.action}</b>
                    <span className="text-slate-600">{new Date(a.at).toLocaleString('en-IN')} · {a.actor_ein}</span>
                    {a.note && <span className="w-full text-slate-600">{a.note}</span>}
                  </li>
                ))}
                {actionCount > 0 && (
                  <li className="text-xs text-slate-600">
                    {actionCount} action{actionCount === 1 ? '' : 's'} recorded in this session. Reopen the account to
                    read them back from the audit trail.
                  </li>
                )}
              </ul>
            </section>
          )}
        </div>
      )}
    </Dialog>
  )
}
