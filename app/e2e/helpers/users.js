// Demo users, straight out of rrsquad-platform/seeds/users.yaml. These are not real
// people — see that file's header.
//
// SEED_INITIAL_PASSWORD is a LOCAL-DEV-ONLY default: it only ever unlocks a Postgres
// container on 127.0.0.1 that global-setup.js just reset to this exact value. It is not a
// real credential for anything, and it must match whatever global-setup.js passed to
// `python -m app.seeds --reset-passwords` (both read the same env var, so they cannot
// drift apart unless something overrides one without the other).
export const SEED_INITIAL_PASSWORD = process.env.SEED_INITIAL_PASSWORD || 'DevSeed!Passw0rd-2026'

// The password every spec leaves a demo user on after completing that user's forced
// password change. Also local-dev-only, also not a real credential.
export const FINAL_PASSWORD = process.env.E2E_FINAL_PASSWORD || 'DevChanged!Passw0rd-2026'

export const USERS = Object.freeze({
  admin: Object.freeze({ username: 'a.deshmukh', role: 'admin', label: 'Administrator' }),
  manager: Object.freeze({ username: 'r.venkataraman', role: 'manager', label: 'Manager' }),
  creditOfficer: Object.freeze({
    username: 's.kulkarni',
    role: 'credit_officer',
    label: 'Credit officer',
    scope: Object.freeze(['MSME-CC', 'MSME-TL', 'LAP']),
  }),
  relationshipManager1: Object.freeze({ username: 'v.rathore', role: 'relationship_manager', label: 'Relationship manager' }),
  relationshipManager2: Object.freeze({ username: 'p.nair', role: 'relationship_manager', label: 'Relationship manager' }),
})
