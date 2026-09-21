import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AccountDetail, { arrearsLead, toSeries } from './AccountDetail'
import { renderScreen } from '../test/render'
import {
  B, ROW_WITHOUT_LIMIT, ROW_WITH_LIMIT, account, apiRoutes, envelope, fail, memo, mockApi, ok,
} from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = (accountId, opts) =>
  renderScreen(<AccountDetail accountId={accountId} live onClose={() => {}} />, opts)

describe('arrearsLead — the per-month DPD the drawer used to drop', () => {
  const at = (date, pd, dpd) => ({ date, pd, dpd })

  it('finds the first month in arrears and how far ahead the score crossed Amber', () => {
    const series = [
      at('2026-01', 2, 0), at('2026-02', 9, 0), at('2026-03', 12, 0), at('2026-04', 30, 15),
    ]
    // Amber at 0.07 -> 7%, first crossed in 2026-02; arrears start in 2026-04.
    expect(arrearsLead(series, 0.07)).toEqual({
      month: '2026-04', peak: 15, monthsEarly: 2, flaggedMonth: '2026-02',
    })
  })

  it('returns null when the run published no per-month DPD at all', () => {
    expect(arrearsLead([at('2026-01', 2, null), at('2026-02', 9, null)], 0.07)).toBeNull()
  })

  it('returns null when the account was never in arrears, rather than claiming month one', () => {
    expect(arrearsLead([at('2026-01', 2, 0), at('2026-02', 9, 0)], 0.07)).toBeNull()
  })

  it('reports the arrears without a lead time when the score never crossed Amber first', () => {
    const out = arrearsLead([at('2026-01', 1, 30), at('2026-02', 40, 60)], 0.07)
    expect(out.month).toBe('2026-01')
    expect(out.peak).toBe(60)
    expect(out.monthsEarly).toBeNull()
  })
})

describe('toSeries — the null-utilisation bug', () => {
  const noLimit = ['cash_flow', 'repayment', 'salary']

  it('keeps an absent utilisation absent instead of drawing it at zero', () => {
    const series = toSeries(
      [{ date: '2026-09', pd: 0.4, pd_smooth: 0.4, utilisation: null, inflow: 1000 }],
      noLimit,
    )
    // `null * 100` is 0, which is how a housing borrower came to be drawn at a flat 0%.
    expect(series[0].util).toBeNull()
    expect(series[0].util).not.toBe(0)
  })

  it('still draws a genuine zero as zero', () => {
    const series = toSeries(
      [{ date: '2026-09', pd: 0.4, pd_smooth: 0.4, utilisation: 0, inflow: 1000 }],
      ['utilisation', 'cash_flow'],
    )
    expect(series[0].util).toBe(0)
  })

  it('indexes inflows to the first observed month, not to a null', () => {
    const series = toSeries([
      { date: '2026-08', pd: 0.3, pd_smooth: 0.3, utilisation: null, inflow: null },
      { date: '2026-09', pd: 0.4, pd_smooth: 0.4, utilisation: null, inflow: 200 },
    ], noLimit)
    expect(series[0].inflowIdx).toBeNull()
    expect(series[1].inflowIdx).toBe(100)
  })
})

describe('Account detail', () => {
  it('is a labelled modal dialog', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITH_LIMIT.account_id)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleName(/MSME00001/)
  })

  it('renders "not applicable" — never 0% — for a product with no credit limit', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITHOUT_LIMIT.account_id)
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('Credit-limit use')).toBeInTheDocument())

    const figure = within(dialog).getByText('Credit-limit use').closest('div')
    expect(figure).toHaveTextContent('not applicable')
    expect(figure).not.toHaveTextContent('0%')
    expect(within(dialog).getAllByText(/no drawable limit/i).length).toBeGreaterThan(0)
  })

  it('renders the observed utilisation when there is one', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITH_LIMIT.account_id)
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByText('Credit-limit use')).toBeInTheDocument())
    expect(within(dialog).getByText('Credit-limit use').closest('div')).toHaveTextContent('92%')
  })

  it('shows the channel strip — what the bank can actually see', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITHOUT_LIMIT.account_id)
    const heading = await screen.findByText(/What the bank can actually see/)
    const strip = heading.closest('section')
    expect(within(strip).getByText('Account inflows')).toBeInTheDocument()
    expect(within(strip).getByText('Salary credits')).toBeInTheDocument()
    expect(within(strip).queryByText('Limit utilisation')).not.toBeInTheDocument()
  })

  it('says the band moved when the published one differs', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText(/A manager has moved a threshold since/)).toBeInTheDocument()
  })

  it('says nothing about a live re-band when the account carries no bucket_source', async () => {
    // ROW_WITH_LIMIT's fixture band still differs from its published one (the mismatch
    // banner above), but that is a different fact from `bucket_source` — the two are
    // independent signals and the hint below must not appear on the mismatch alone.
    mockApi(apiRoutes(), { vi })
    render(ROW_WITH_LIMIT.account_id)
    await screen.findByText(/A manager has moved a threshold since/)
    expect(screen.queryByText(/Live re-band/)).not.toBeInTheDocument()
  })

  it('shows a live re-band hint when the band was recomputed against a moved threshold', async () => {
    const payload = account(ROW_WITH_LIMIT)
    payload.data.scores.bucket_source = 'live'
    mockApi(apiRoutes({ [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}`]: ok(payload) }), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText(/Live re-band · threshold change in force/)).toBeInTheDocument()
  })

  it('falls back to the timeline’s published_bucket when the account payload has none', async () => {
    const accountPayload = account(ROW_WITH_LIMIT)
    accountPayload.data.scores.published_bucket = null
    const timelinePayload = envelope(
      [{ date: '2026-09', pd: ROW_WITH_LIMIT.pd, pd_smooth: ROW_WITH_LIMIT.pd_smooth, bucket: ROW_WITH_LIMIT.bucket, utilisation: null, inflow: null, dpd: null }],
      { total: 1, published_bucket: 'amber' },
    )
    mockApi(apiRoutes({
      [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}`]: ok(accountPayload),
      [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}/timeline`]: ok(timelinePayload),
    }), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText(/A manager has moved a threshold since/)).toBeInTheDocument()
  })

  it('shows the memo and its review disclaimer', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText(/Early-warning memo — account MSME00001/)).toBeInTheDocument()
    expect(screen.getByText(/Review before use/)).toBeInTheDocument()
  })

  it('offers only the contract’s action enum', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITH_LIMIT.account_id)
    const select = await screen.findByLabelText('Action')
    expect([...select.options].map((o) => o.value)).toEqual([
      'acknowledged', 'contacted_borrower', 'site_visit', 'restructure_proposed',
      'escalated', 'classified_sma1', 'false_positive', 'closed',
    ])
  })

  it('records an action and says, out loud, that it is now in the audit log', async () => {
    const api = mockApi(apiRoutes({
      [`POST ${B}/drishti/account/MSME00001/action`]: ok(envelope({
        id: 1, account_id: 'MSME00001', action: 'site_visit', note: 'visited',
        at: '2026-09-16T10:00:00Z', actor_ein: 'EIN-100237',
      })),
    }), { vi })
    render(ROW_WITH_LIMIT.account_id)

    await userEvent.selectOptions(await screen.findByLabelText('Action'), 'site_visit')
    await userEvent.type(screen.getByLabelText(/Note/), 'visited')
    await userEvent.click(screen.getByRole('button', { name: 'Record action' }))

    const status = await screen.findByText(/“Site visit” recorded against MSME00001/)
    expect(status).toBeInTheDocument()
    expect(screen.getByText(/Recorded in the append-only audit log/)).toBeInTheDocument()
    // The confirmation must be inside a live region, or a screen-reader user never hears it.
    expect(status.closest('[role="status"]')).toHaveAttribute('aria-live', 'polite')

    const posted = api.calls.find((c) => c.method === 'POST')
    expect(posted.body).toEqual({ action: 'site_visit', note: 'visited' })
  })

  it('saves an edited memo through PUT and confirms it', async () => {
    const api = mockApi(apiRoutes({
      [`PUT ${B}/drishti/account/MSME00001/memo`]: ok(envelope({ account_id: 'MSME00001', memo: 'rewritten', generated: false })),
    }), { vi })
    render(ROW_WITH_LIMIT.account_id)

    await userEvent.click(await screen.findByRole('button', { name: /Edit/ }))
    const box = screen.getByLabelText('Memo text')
    await userEvent.clear(box)
    await userEvent.type(box, 'rewritten')
    await userEvent.click(screen.getByRole('button', { name: 'Save memo' }))

    expect(await screen.findByText(/Memo for MSME00001 saved/)).toBeInTheDocument()
    expect(api.calls.find((c) => c.method === 'PUT').body).toEqual({ memo: 'rewritten' })
  })

  it('says the account is not in this run on a 404, rather than showing a broken screen', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/account/MSME00001`]: fail(404, { code: 'not_found', message: 'No such account.' }) }), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByTestId('state-error')).toHaveTextContent('That account is not in this model run')
  })

  it('degrades when the timeline fails but the account loads', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/account/MSME00001/timeline`]: fail(503, { code: 'upstream_error', message: 'Busy.' }) }), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText(/Could not load the trajectory/)).toBeInTheDocument()
    // the rest of the account is still there
    expect(screen.getByText(/Why the model flagged this account/)).toBeInTheDocument()
  })

  it('shows an empty memo state rather than a blank panel', async () => {
    mockApi(apiRoutes({
      [`${B}/drishti/account/MSME00001/memo`]: ok(envelope({ ...memo().data, memo: '', generated: false })),
    }), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText('No memo yet')).toBeInTheDocument()
  })

  it('disables the write controls in the frozen bundle instead of faking a record', async () => {
    const snapshot = {
      meta: { reference_month: '2026-09', provenance: {} },
      portfolio_summary: { red_thr: 0.5, amber_thr: 0.2 },
      portfolio: [{ account_id: 'SNAP1', portfolio: 'Agri', pd: 0.8, bucket: 'red', sanctioned: 100, reasons: [], channels_present: ['repayment'] }],
      timelines: { SNAP1: [] }, memos: { SNAP1: 'frozen memo' }, metrics: {}, rigor: {},
    }
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (String(url).endsWith('demo_data.json')) {
        return { ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => snapshot }
      }
      throw new Error(`unexpected fetch ${url}`)
    }))
    renderScreen(<AccountDetail accountId="SNAP1" live={false} onClose={() => {}} />, { mode: 'static' })

    expect(await screen.findByRole('button', { name: 'Record action' })).toBeDisabled()
    expect(screen.getByText(/no audit log to write to/)).toBeInTheDocument()
  })
})

describe('Account drawer — arrears panel', () => {
  it('draws the month-by-month arrears the export now carries', async () => {
    mockApi(apiRoutes(), { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText('Arrears, month by month')).toBeInTheDocument()
    expect(screen.getByText(/Days past due as the core banking system recorded them/)).toBeInTheDocument()
  })

  it('says the run published none rather than drawing a flat line at zero', async () => {
    mockApi({
      ...apiRoutes(),
      [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}/timeline`]: ok(envelope(
        ['2026-08', '2026-09'].map((date) => ({
          date, pd: 0.4, pd_smooth: 0.4, bucket: 'red', utilisation: 0.5, inflow: 1000, dpd: null,
        })),
        { total: 2, reference_month: '2026-09' },
      )),
    }, { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText(/published no month-by-month days-past-due/)).toBeInTheDocument()
  })
})

describe('Account drawer — whose book it is', () => {
  it('names the branch, the IFSC and the relationship manager when the platform sends them', async () => {
    const account = apiRoutes()[`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}`]
    const body = JSON.parse(JSON.stringify(account.body ?? account))
    mockApi({
      ...apiRoutes(),
      [`${B}/drishti/account/${ROW_WITH_LIMIT.account_id}`]: ok(envelope({
        ...(body.data ?? body),
        branch_name: 'Fort Branch',
        branch_code: 'BR-0207',
        ifsc: 'IBKL0000105',
        rm_name: 'Sneha Kulkarni',
        rm_ein: 'EIN-100358',
      })),
    }, { vi })
    render(ROW_WITH_LIMIT.account_id)
    expect(await screen.findByText('Fort Branch')).toBeInTheDocument()
    expect(screen.getByText('IBKL0000105')).toBeInTheDocument()
    expect(screen.getByText('Sneha Kulkarni')).toBeInTheDocument()
  })
})

