// Playwright config for the DRISHTi e2e suite.
//
// The backend (uvicorn :8001), its Postgres (rrsquad-pg-dev on :55432) and the app's own
// `vite preview` (:4173, IPv6-only — use `localhost`, not `127.0.0.1`) are expected to
// already be running; see e2e/global-setup.js, which verifies both and refuses to run the
// suite against a build that is not there rather than silently starting a different one.
//
// `workers: 1` / `fullyParallel: false` is deliberate, not a perf default: every spec signs
// in as one of five shared demo users against one shared dev database (seeds/users.yaml —
// other lanes use the same Postgres container), so two specs touching the same user's
// password at once would race. Running sequentially trades a slower suite for a
// deterministic one.
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.js',
  globalSetup: './e2e/global-setup.js',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  // Generous on purpose: this dev box has been observed under very heavy concurrent load
  // (other lanes' own browser/test processes — load average in the 30s-60s is not unusual
  // here), which stalls the backend's argon2id login hash (deliberately memory-hard, per
  // its own docs) for several seconds at a time. That is host contention, not the app
  // being slow — see the suite's final report — so timeouts are set to ride it out rather
  // than flake on it.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: './e2e/test-results',
  reporter: [
    ['list'],
    ['html', { outputFolder: './e2e/report', open: 'never' }],
  ],
  use: {
    // vite preview only binds the IPv6 loopback — 127.0.0.1 does not connect. Trailing
    // slash matters: WHATWG URL resolution means a relative page path ('watchlist')
    // joins onto this whole base, while a leading-slash path ('/api/...') resolves
    // against the origin instead — that split is deliberate, see e2e/helpers/auth.js.
    baseURL: 'http://localhost:4173/drishti/',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
})
