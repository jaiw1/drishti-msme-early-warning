# DRISHTi demo — narration transcript

Recorded via `video-autopilot/drishti-autopilot.mjs` against the **static demo build**:
`app/` built from `main` with no `VITE_API_BASE`, served by a plain static file server
that answers every `/api/*` request with an immediate 404 and proxies nothing (see
`video-autopilot/static-only-server.js`) — no `rrsquad-platform`, no Postgres, no login.
`src/lib/mode.js::resolveMode()` sees the failed health check and resolves to
`MODE.STATIC`, the app's own first-class "frozen demo bundle" mode (the same one shipped
at `https://drishti-ews.vercel.app`): every read comes straight from the committed
`app/public/demo_data.json`, and every mutating control (record an action, change a
threshold, the admin audit log) is honestly disabled or unavailable, with its own
on-screen explanation, rather than faked. Recorded 2026-09-21, against `main`
(msme-ews@28204bd). Every number below is read directly off the screen at the timestamp
given; none is asserted from memory. **Bold** marks the words the on-screen karaoke
caption highlights.

The recorded file has no spoken audio (no human narrator was available to this
autonomous run) — the on-screen caption bar carries this exact text, word-synced, burned
into the video. A presenter can read this transcript aloud over the video, live, during
the demo slot.

Total run time: **≈2:35** (well inside the 3-minute cap the deck template requires).

## Why this is a shorter, simpler recording than the 17 Sep take

The bank's numbers changed today (Red-band precision rose to 88.6% on a re-fit policy
fold — see below), and the deck template now requires a video under 3 minutes, not 4. The
17 Sep recording drove a real backend (login, three roles, live writes: record an action,
change a threshold, verify the audit chain) and ran ≈3:46. Re-doing that same tour and
also cutting a minute would have meant speaking over it faster, which is not how this
project narrates honest numbers. Instead this take uses the app's own **static demo**
mode — no backend needed at all, and every screen already degrades honestly when a write
isn't possible, which is most of what the login/role tour existed to demonstrate anyway.
Concretely, this means:

- **No sign-in, no role switching.** Static mode has no session; every route is open.
- **"Record action" is shown, not clicked.** The button is visibly disabled, with its own
  on-screen text: *"This is the frozen demo bundle. There is no audit log to write to, so
  the control is disabled rather than pretending to record something."*
- **The threshold-change and admin/audit-log scenes are gone.** `Thresholds.jsx` does not
  even render a "Change thresholds" button in static mode (`editable = live && ...`), and
  `Admin.jsx` has no static fallback at all — it would show a live 404 error with no
  backend. Neither is invented or patched around; both are simply not part of this tour.
- **The account used on 17 Sep, MSME33100, is not in this build.**
  `app/public/demo_data.json` carries a ~700-account *sample* of individual rows (the
  aggregate metrics — 245/458/12,057 etc. — are the true full 12,760-account book).
  MSME33100 isn't in the sample. The hero account below, **MSME16350**, is — and usefully
  tells the same "not applicable" story (a LAP account has no revolving credit limit).
- **The validation table is honestly empty.** `snapshotValidation()` returns
  `available: false` on purpose — *"The validation report lives in the platform database
  and is attached to a published model run. This frozen bundle has no backend to read it
  from."* The 26-criteria breakdown (16 pass / 6 report-only / 4 disclosed fails) is real
  and current (`validation/report/report.json`, unchanged by today's merge) but is not
  narrated here as an on-screen figure, because it is not one in this build — see
  `README.md` / `MODEL_CARD.md` for the citable version.

---

**0:00–0:12 — Watch-list overview**
> This is DRISHTi's **static demo** build — no login, no backend — reading a frozen
> snapshot of IDBI's **12,760**-account MSME book across all **eight** lending
> portfolios: **245** in Red, **458** in Amber.

**0:12–0:35 — Hero account: headline + not-applicable**
> Account MSME16350 — loan against property, **₹15.4 lakh** sanctioned, a **54%** default
> probability, **80 days** past due — first flagged **5 months** before that happened.
> Credit-limit use itself reads **not applicable**: this product has no drawable limit,
> so there is nothing to report — not a hidden zero.

**0:35–0:51 — Reasons + memo**
> Three reasons drove the flag: **79 days** past due, only **34%** of what was demanded
> collected, a short collection pattern. A memo is already drafted — AI-generated, human
> review required — recommending credit review and borrower engagement.

**0:51–1:07 — What action: record (honestly disabled)**
> Recording what the officer did would be one audited click. This frozen bundle is
> honest about the limit instead: the control is **disabled** rather than pretending to
> write to an audit log that does not exist here.

**1:07–1:26 — What the evidence supports: portfolio risk**
> Portfolio risk, across all eight products. One model is only a real claim if it ranks
> risk inside **every** one of them — Red-band precision runs from retail-unsecured's
> **71%** up to Education's and Auto's **100%**, on bands as thin as six accounts, which
> is why each one carries its interval.

**1:26–1:48 — Honesty headline**
> The honesty headline: **88.6%** of Red-flagged accounts went NPA within eight months, n
> equals **245** — not raw accuracy; flagging nobody would already score **97.3%**, since
> only **2.7%** of this book goes bad, beside the **16.1%** of NPAs this operating point
> still missed.

**1:48–2:04 — Why precision rose**
> That rise from **84.5%** is the Red threshold moving up on a held-out policy fold, not
> the model improving — held at the old threshold, this model's own precision actually
> falls.
>
> *(This comparison — 84.5% vs 88.6%, and what moved and why — is MODEL_CARD.md §8's own
> documented record, not a number this build's screen shows side by side; the screen
> shows the current 88.6%/245 figure only. See "What --verify could not confirm on
> screen" below.)*

**2:04–2:16 — Validation, honestly unavailable**
> Even the validation table is honest about its own limit here: the **26** pre-registered
> criteria live on the platform database, so this frozen bundle says so rather than
> faking a pass.

**2:16–2:28 — Data sources**
> Data sources: no screen in this product shows the bank's production numbers — every
> family here is a **fixture or simulated**, and every screen says so.

**2:28–2:34 — Sign-off**
> DRISHTi advises. The credit officer decides.

---

## What `--verify` confirmed on screen (regex-asserted, not just eyeballed)

`drishti-autopilot.mjs --verify` asserts these on every relevant scene and fails loudly
if any is missing:

- Watch-list: `12,760`, `245`, `458`
- Hero account: `₹15.4 L`, `54%`, `80` (days past due), `5 mo before trouble`, `not
  applicable`
- Portfolio risk: `71.4%` (Retail-Unsecured), `100.0%` (Education / Auto)
- Model & Metrics: `88.6%`, `245`, `97.3%`, `2.7%`, `16.1%`, `No validation report is
  attached`
- Data sources: `No screen in this product is showing the bank`

## What `--verify` could not confirm on screen

- **The 84.5% → 88.6% comparison and its threshold-not-model explanation.** This is a
  documented fact from `MODEL_CARD.md` §8 / `README.md` (the operating point moved from
  0.2720 to 0.3437 on a held-out policy fold; holding the old threshold, the new model's
  own precision is 82.3%, i.e. *down* 2.2pp) — but this build's Model & Metrics screen
  shows only the current 88.6%/245 figure, not the 84.5% comparator or the "policy fold"
  framing side by side with it. Spoken as context a presenter would reasonably add, not
  asserted as a rendered pixel.
- **The 16/6/4 validation criteria breakdown.** Real (`validation/report/report.json`,
  unchanged since 2026-09-17) but genuinely not rendered anywhere in this static build —
  see above.
- **The exact Red/Amber thresholds (34.37% / 6.93%) and the ecosystem/contagion panel.**
  Both render correctly in this build but are not part of this cut; the contagion lens is
  now explicitly labelled "Illustrative" on screen as of msme-ews@28204bd (a same-day
  merge), which this recording's build picked up but does not narrate — it is an appendix
  exhibit, not covered in a 3-minute cut.

## Superseded

The 17 Sep recording is kept at `docs/demo/drishti-demo-2026-09-17.mp4` (≈3:46, real
backend, MSME33100, old 84.5%/n=283 numbers, now stale). This file replaces it as the
current demo video.
