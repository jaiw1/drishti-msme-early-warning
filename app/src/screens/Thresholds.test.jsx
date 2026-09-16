import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Thresholds from './Thresholds'
import { renderScreen, session } from '../test/render'
import { B, apiRoutes, envelope, fail, mockApi, ok, threshold } from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = (opts) => renderScreen(<Thresholds />, { path: '/threshold', ...opts })

describe('Thresholds', () => {
  it('shows the lines in force and the ones the run published, when they differ', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const red = (await screen.findByText('Red — act now')).parentElement
    expect(red).toHaveTextContent('50.00%')
    expect(red).toHaveTextContent('run published 91.55%')
    const amber = screen.getByText('Amber — watch').parentElement
    expect(amber).toHaveTextContent('20.00%')
    expect(amber).toHaveTextContent('run published 1.00%')
  })

  it('reads the cost rationale the run published', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText('Why the lines sit where they do')).toBeInTheDocument()
    expect(screen.getByText('Cost of a missed NPA')).toBeInTheDocument()
    expect(screen.getByText('301.3 : 1')).toBeInTheDocument()
  })

  it('reads DM-5’s method / cost_params / alternatives spelling too', async () => {
    mockApi(apiRoutes({
      [`${B}/drishti/threshold`]: ok(envelope({
        ...threshold().data,
        cost_model: {
          method: 'expected-cost minimisation',
          cost_params: { horizon_months: 8, discount: 0 },
          alternatives: [
            { red_thr: 0.2, cost: 100, missed: 1, fp: 40 },
            { red_thr: 0.6, cost: 400, missed: 9, fp: 4 },
          ],
        },
      })),
    }), { vi })
    render()
    expect(await screen.findByText('expected-cost minimisation')).toBeInTheDocument()
    expect(screen.getByText('horizon months')).toBeInTheDocument()
  })

  it('degrades honestly when the run published no cost model at all', async () => {
    mockApi(apiRoutes({
      [`${B}/drishti/threshold`]: ok(envelope({ ...threshold().data, cost_model: null })),
    }), { vi })
    render()
    expect(await screen.findByText('This run published no cost rationale')).toBeInTheDocument()
  })

  it('lists the change history with each justification', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const table = await screen.findByRole('table', { name: /threshold changes/i })
    expect(within(table).getByText(/Widened the watch tier/)).toBeInTheDocument()
    // the history shows the move, both sides of it
    expect(within(table).getByText(/91\.55%/)).toHaveTextContent('91.55% → 50.00%')
  })

  it('says so, rather than showing an empty table, when nothing has ever changed', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/threshold`]: ok(threshold({ history: false })) }), { vi })
    render()
    expect(await screen.findByText('No threshold has ever been changed')).toBeInTheDocument()
  })

  it('hides the change control from a credit officer and explains why', async () => {
    mockApi(apiRoutes(), { vi })
    render({ user: session('credit_officer') })
    await screen.findByText('Why the lines sit where they do')
    expect(screen.queryByRole('button', { name: /Change thresholds/ })).not.toBeInTheDocument()
    expect(screen.getByText(/changing them is not your role’s to do/)).toBeInTheDocument()
  })

  it('opens a focus-trapped confirmation dialog for a manager', async () => {
    mockApi(apiRoutes(), { vi })
    render({ user: session('manager') })
    await userEvent.click(await screen.findByRole('button', { name: /Change thresholds/ }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleName('Change the Red and Amber thresholds')
    await waitFor(() => expect(screen.getByLabelText(/Red — act now/)).toHaveFocus())
  })

  it('refuses to submit a change that would make Amber unreachable', async () => {
    mockApi(apiRoutes(), { vi })
    render({ user: session('manager') })
    await userEvent.click(await screen.findByRole('button', { name: /Change thresholds/ }))
    const amber = screen.getByLabelText(/Amber — watch/)
    await userEvent.clear(amber)
    await userEvent.type(amber, '80')
    await userEvent.type(screen.getByLabelText(/Justification/), 'a long enough justification')
    expect(screen.getByText(/Amber must sit below Red/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm and apply' })).toBeDisabled()
  })

  it('requires a justification before it will let the change through', async () => {
    mockApi(apiRoutes(), { vi })
    render({ user: session('manager') })
    await userEvent.click(await screen.findByRole('button', { name: /Change thresholds/ }))
    expect(screen.getByText(/justification of at least 10 characters is required/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm and apply' })).toBeDisabled()
  })

  it('PUTs the change and confirms that nothing was re-scored', async () => {
    const api = mockApi(apiRoutes({
      [`PUT ${B}/drishti/threshold`]: ok(envelope({
        red_thr: 0.6, amber_thr: 0.25, source: 'threshold_change', threshold_change_id: 2,
        justification: 'Tightened after the Q3 review of the trading book.',
        rebucketed: { red: 12, amber: 30, green: 118 },
        rescored: false,
        note: 'Bands are recomputed on read. No score row was modified.',
      })),
    }), { vi })
    render({ user: session('manager') })

    await userEvent.click(await screen.findByRole('button', { name: /Change thresholds/ }))
    const red = screen.getByLabelText(/Red — act now/)
    await userEvent.clear(red); await userEvent.type(red, '60')
    const amber = screen.getByLabelText(/Amber — watch/)
    await userEvent.clear(amber); await userEvent.type(amber, '25')
    await userEvent.type(screen.getByLabelText(/Justification/), 'Tightened after the Q3 review of the trading book.')

    // The confirm button only becomes available once the form is valid; clicking it while
    // it is still disabled is a silent no-op, which is how this test used to flake.
    const confirm = screen.getByRole('button', { name: 'Confirm and apply' })
    await waitFor(() => expect(confirm).toBeEnabled())
    await userEvent.click(confirm)

    expect(await screen.findByText(/Thresholds changed to Red ≥ 60\.00%, Amber ≥ 25\.00%/)).toBeInTheDocument()
    expect(screen.getByText(/No score row was modified/)).toBeInTheDocument()

    const put = api.calls.find((c) => c.method === 'PUT')
    expect(put.body).toEqual({
      red_thr: 0.6, amber_thr: 0.25, justification: 'Tightened after the Q3 review of the trading book.',
    })
  })

  it('reports a rejected change instead of pretending it worked', async () => {
    mockApi(apiRoutes({
      [`PUT ${B}/drishti/threshold`]: fail(403, { code: 'forbidden', message: 'Your role does not permit this.' }),
    }), { vi })
    render({ user: session('manager') })

    await userEvent.click(await screen.findByRole('button', { name: /Change thresholds/ }))
    await userEvent.type(screen.getByLabelText(/Justification/), 'a long enough justification')
    const confirm = screen.getByRole('button', { name: 'Confirm and apply' })
    await waitFor(() => expect(confirm).toBeEnabled())
    await userEvent.click(confirm)

    expect(await screen.findByText('Could not change the thresholds.')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument() // the dialog stays open on failure
  })

  it('shows the error state when the thresholds cannot be read', async () => {
    mockApi(apiRoutes({ [`${B}/drishti/threshold`]: fail(500, { code: 'internal_error', message: 'Boom.' }) }), { vi })
    render()
    expect(await screen.findByTestId('state-error')).toHaveTextContent('Could not load the thresholds')
  })
})
