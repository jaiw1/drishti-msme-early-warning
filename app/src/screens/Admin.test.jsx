import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Admin from './Admin'
import { renderScreen, session } from '../test/render'
import { B, apiRoutes, auditVerify, envelope, fail, mockApi, ok } from '../test/fixtures/api'

afterEach(() => vi.unstubAllGlobals())

const render = () => renderScreen(<Admin />, { path: '/admin', user: session('admin') })
const CO_ID = '98da0daa-fab5-4617-b151-7fa3a2becf6b'

describe('Administration — users', () => {
  it('lists users with their role and scope', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    const table = await screen.findByRole('table', { name: /users, their roles and scope/i })
    expect(within(table).getByRole('rowheader', { name: /s\.kulkarni/ })).toBeInTheDocument()
    expect(within(table).getByText('MSME-CC, MSME-TL, LAP')).toBeInTheDocument()
  })

  it('warns that a credit officer with no scope sees nothing', async () => {
    mockApi(apiRoutes({
      [`${B}/admin/users`]: ok(envelope([
        { id: 'x', username: 'new.officer', full_name: 'New Officer', role: 'credit_officer', scope: [], is_active: true },
      ], { total: 1 })),
    }), { vi })
    render()
    expect(await screen.findByText('no portfolios — sees nothing')).toBeInTheDocument()
  })

  it('changes a role through POST /admin/users/{id}/role and confirms it', async () => {
    const api = mockApi(apiRoutes({
      [`POST ${B}/admin/users/${CO_ID}/role`]: ok(envelope({ id: CO_ID, username: 's.kulkarni', role: 'manager', is_active: true })),
    }), { vi })
    render()
    await userEvent.selectOptions(await screen.findByLabelText('Role for s.kulkarni'), 'manager')
    expect(await screen.findByText('s.kulkarni is now Manager.')).toBeInTheDocument()
    expect(api.calls.find((c) => c.method === 'POST').body).toMatchObject({ role: 'manager' })
  })

  it('deactivates a user, then activates them back', async () => {
    let active = true
    const api = mockApi(apiRoutes({
      [`${B}/admin/users`]: () => ok(envelope([
        { id: CO_ID, username: 's.kulkarni', full_name: 'Sneha Kulkarni', role: 'credit_officer', scope: ['LAP'], is_active: active },
      ], { total: 1 })),
      [`POST ${B}/admin/users/${CO_ID}/deactivate`]: () => { active = false; return ok(envelope({ id: CO_ID, username: 's.kulkarni', role: 'credit_officer', is_active: false })) },
      [`POST ${B}/admin/users/${CO_ID}/activate`]: () => { active = true; return ok(envelope({ id: CO_ID, username: 's.kulkarni', role: 'credit_officer', is_active: true })) },
    }), { vi })
    render()

    await userEvent.click(await screen.findByRole('button', { name: /Deactivate/ }))
    expect(await screen.findByText('s.kulkarni deactivated.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Deactivated')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /Activate/ }))
    expect(await screen.findByText('s.kulkarni activated.')).toBeInTheDocument()
    expect(api.calls.filter((c) => c.method === 'POST')).toHaveLength(2)
  })

  it('shows a reset password exactly once, and says it is stored nowhere', async () => {
    mockApi(apiRoutes({
      [`${B}/admin/users`]: ok(envelope([
        { id: CO_ID, username: 's.kulkarni', full_name: 'Sneha Kulkarni', role: 'credit_officer', scope: ['LAP'], is_active: true },
      ], { total: 1 })),
      [`POST ${B}/admin/users/${CO_ID}/reset-password`]: ok(envelope({
        user_id: CO_ID, username: 's.kulkarni', initial_password: 'Tmp-One-Time-Value',
        must_change_password: true, note: 'The user must change this at first sign-in.',
      })),
    }), { vi })
    render()
    await userEvent.click(await screen.findByRole('button', { name: /Reset password/ }))

    const dialog = await screen.findByTestId('reset-result')
    expect(within(dialog).getByText('Tmp-One-Time-Value')).toBeInTheDocument()
    expect(within(dialog).getByText(/stored nowhere else/)).toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: /I have handed it over/ }))
    await waitFor(() => expect(screen.queryByText('Tmp-One-Time-Value')).not.toBeInTheDocument())
  })

  it('creates a user, with a portfolio scope when the role is a credit officer', async () => {
    const api = mockApi(apiRoutes({
      [`POST ${B}/admin/users`]: ok(envelope({ id: 'new', username: 'n.new', role: 'credit_officer', initial_password: 'x' })),
    }), { vi })
    render()
    await userEvent.click(await screen.findByRole('button', { name: /Create user/ }))

    const dialog = screen.getByTestId('create-user-dialog')
    await userEvent.type(within(dialog).getByLabelText('Username'), 'n.new')
    await userEvent.click(within(dialog).getByLabelText('Agri'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create user' }))

    await waitFor(() => expect(api.calls.find((c) => c.path === `${B}/admin/users` && c.method === 'POST')).toBeTruthy())
    expect(api.calls.find((c) => c.method === 'POST').body).toEqual({
      username: 'n.new', role: 'credit_officer', scope: ['Agri'],
    })
  })

  it('rejects a malformed employee number before it reaches the server', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    await userEvent.click(await screen.findByRole('button', { name: /Create user/ }))
    const dialog = screen.getByTestId('create-user-dialog')
    await userEvent.type(within(dialog).getByLabelText('Username'), 'n.new')
    await userEvent.type(within(dialog).getByLabelText('Employee number'), 'nope')
    expect(within(dialog).getByText('Must look like EIN-100123.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Create user' })).toBeDisabled()
  })

  it('reports a failed administrative action instead of swallowing it', async () => {
    mockApi(apiRoutes({
      [`${B}/admin/users`]: ok(envelope([
        { id: CO_ID, username: 's.kulkarni', full_name: 'Sneha Kulkarni', role: 'credit_officer', scope: ['LAP'], is_active: true },
      ], { total: 1 })),
      [`POST ${B}/admin/users/${CO_ID}/deactivate`]: fail(409, { code: 'conflict', message: 'That is the last administrator.' }),
    }), { vi })
    render()
    await userEvent.click(await screen.findByRole('button', { name: /Deactivate/ }))
    expect(await screen.findByText('That administrative action failed.')).toBeInTheDocument()
    expect(screen.getByText('That is the last administrator.')).toBeInTheDocument()
  })

  it('shows the error state when users cannot be read', async () => {
    mockApi(apiRoutes({ [`${B}/admin/users`]: fail(500, { code: 'internal_error', message: 'Boom.' }) }), { vi })
    render()
    expect(await screen.findByText('Could not load users')).toBeInTheDocument()
  })
})

describe('Administration — audit log', () => {
  it('lists entries and explains that the table is append-only', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    expect(await screen.findByText(/refuses UPDATE and DELETE on this table/)).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: /audit entries/i })
    expect(within(table).getByText('request.get.admin.users')).toBeInTheDocument()
  })

  it('reports an intact chain with the number of rows it recomputed', async () => {
    mockApi(apiRoutes(), { vi })
    render()
    await userEvent.click(await screen.findByRole('button', { name: /Verify chain/ }))
    const banner = (await screen.findByText(/Chain intact/)).closest('p')
    expect(banner).toHaveTextContent('11 rows recomputed')
    expect(banner.closest('[role="status"]')).toHaveAttribute('aria-live', 'polite')
  })

  it('names the first bad row when the chain is broken', async () => {
    mockApi(apiRoutes({ [`POST ${B}/admin/audit/verify`]: ok(auditVerify({ ok: false })) }), { vi })
    render()
    await userEvent.click(await screen.findByRole('button', { name: /Verify chain/ }))
    const banner = (await screen.findByText(/Chain broken/)).closest('p')
    expect(banner).toHaveTextContent('first bad row is id 7')
    expect(banner).toHaveTextContent('hash mismatch')
  })

  it('says verification failed rather than claiming the chain is fine', async () => {
    mockApi(apiRoutes({ [`POST ${B}/admin/audit/verify`]: fail(503, { code: 'upstream_error', message: 'Database busy.' }) }), { vi })
    render()
    await userEvent.click(await screen.findByRole('button', { name: /Verify chain/ }))
    expect(await screen.findByText(/Verification could not be completed/)).toBeInTheDocument()
  })

  it('sends only the filters the contract accepts', async () => {
    const api = mockApi(apiRoutes(), { vi })
    render()
    await screen.findByRole('table', { name: /audit entries/i })
    await userEvent.type(screen.getByLabelText('Actor'), 'a.deshmukh')
    await userEvent.type(screen.getByLabelText('Action'), 'auth.password.changed')
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }))

    await waitFor(() => {
      const last = api.calls.filter((c) => c.path === `${B}/admin/audit`).at(-1)
      expect(last.url).toContain('actor=a.deshmukh')
      expect(last.url).toContain('action=auth.password.changed')
    })
  })

  it('says the filters matched nothing, not that there is nothing', async () => {
    mockApi(apiRoutes({ [`${B}/admin/audit`]: ok(envelope([], { total: 0 })) }), { vi })
    render()
    expect(await screen.findByText('No entries match those filters')).toBeInTheDocument()
  })
})
