// Runs once before the whole suite.
//
// Verifies the backend and the preview build are actually reachable (per the harness's own
// instructions: they are expected to already be running — this suite never starts or
// restarts them itself), then resets every demo user in seeds/users.yaml to
// must_change_password + SEED_INITIAL_PASSWORD. That reset is what makes the suite
// repeatable run after run regardless of what a previous run (or a human poking at the
// app) left the passwords at — see rrsquad-platform/seeds/users.yaml.
//
// This Postgres container is shared with other lanes' own work; resetting passwords only
// touches the five seeded demo users' auth fields (password hash, must_change_password,
// failed_attempts, locked_until), which is exactly what the platform's own seeder is for.
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

const BACKEND_HEALTH_URL = 'http://127.0.0.1:8001/api/v1/meta/health'
const PREVIEW_URL = 'http://localhost:4173/drishti/'
const PLATFORM_DIR = '/Users/jaiwadhwa/Desktop/Jai/personal/IDBI Innovate/rrsquad-platform'
const DATABASE_URL =
  process.env.DATABASE_URL || 'postgresql+psycopg://rrsquad_app:devonly_app_pw@127.0.0.1:55432/rrsquad'

// Local-dev-only bootstrap value. Must match whatever e2e/helpers/users.js expects as the
// seed password for a freshly-reset account; both read the same env var so they can only
// drift if someone overrides one without the other.
const SEED_INITIAL_PASSWORD = process.env.SEED_INITIAL_PASSWORD || 'DevSeed!Passw0rd-2026'

// Playwright's own startup (spawning the browser, workers, etc.) competes for the same
// machine right as this runs, which has been observed making a single 5s fetch time out
// even though a plain `curl` to the same URL answers instantly — so retry a few times
// before concluding the service is actually down, not just momentarily slow to schedule.
async function ping(url, label, hint, attempts = 3) {
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(8000) })
      if (!response.ok) {
        throw new Error(`answered HTTP ${response.status}, expected 2xx`)
      }
      return
    } catch (error) {
      lastError = error
      if (attempt < attempts) await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  }
  throw new Error(
    `${label} is not reachable at ${url} after ${attempts} attempts (${lastError.message}).\n` +
      `This suite expects it already running — do not start it from here. ${hint}`,
  )
}

export default async function globalSetup() {
  await ping(
    BACKEND_HEALTH_URL,
    'Backend',
    'Start it with: uvicorn app.main:app --port 8001 (from rrsquad-platform/, with DATABASE_URL set).',
  )
  await ping(
    PREVIEW_URL,
    'Preview build',
    'Build and serve it with: npm run build -- --base /drishti/ && VITE_DEV_API_PROXY=http://127.0.0.1:8001 npx vite preview --port 4173 --strictPort (from app/).',
  )

  // This shared dev box has been observed under very heavy concurrent load from other
  // lanes' own processes (load average in the 40s-60s, dozens of Chrome helpers) which is
  // enough to blow past Postgres's statement_timeout on an ordinary upsert. That is host
  // contention, not a broken seeder — retry rather than fail the whole suite on it.
  let lastError
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const { stdout } = await execFileAsync(
        '.venv/bin/python',
        ['-m', 'app.seeds', '--reset-passwords'],
        {
          cwd: PLATFORM_DIR,
          env: { ...process.env, DATABASE_URL, SEED_INITIAL_PASSWORD },
          timeout: 45_000,
        },
      )
      console.log('[global-setup] reset seed-user passwords:\n' + stdout.trim())
      return
    } catch (error) {
      lastError = error
      const detail = error.stderr || error.stdout || error.message
      console.warn(`[global-setup] seed reset attempt ${attempt}/3 failed:\n${detail}`)
      if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 3000))
    }
  }
  throw new Error(`seed reset failed after 3 attempts: ${lastError.stderr || lastError.message}`)
}
