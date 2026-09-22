# DRISHTi demo — narration transcript

Recorded against a **live rrsquad-platform
backend**: `app/` built from `main` (msme-ews@e225368) with `VITE_API_BASE` unset and a
same-origin dev-server proxy (`VITE_DEV_API_PROXY`) to a real `uvicorn` process
(rrsquad-platform@7312ae5) backed by its own local dev Postgres database, migrated,
seeded with the five real demo users, and loaded with the committed
`app/public/demo_data.json` (reshaped into the platform's raw export contract — key
renames and a nested `scores` object — and loaded with `--allow-invalid`, because that
contract gained fields, `cif_id`/`scores`/`provenance` among them, after this export was
generated; every number the export carries is unchanged by the reshape). This is a real
signed-in session end to end: real cookies, real CSRF, a real password change out of
band before recording, real role checks, and one real write to the append-only,
hash-chained audit log. Recorded 2026-09-21. Every number below is read directly off the
screen at the timestamp given; none is asserted from memory.

The recorded file carries a spoken voiceover — Microsoft neural text-to-speech
(`en-IN-NeerjaNeural`) reading this exact transcript, timed to the on-screen action. No
caption bar, no karaoke highlighting.

Total run time: **≈2:50** (well inside the 3-minute cap the deck template requires).

## Why this replaces the 21 Sep static-demo take

An earlier same-day take re-recorded this video against the app's **static demo** mode (no
login, no backend, every write honestly disabled) to hit the 3-minute cap quickly. That
hid the product's actual differentiators — role-scoped auth, a real audited write, the
live validation/audit surface — which is exactly what a bank reviewer needs to see. This
take goes back to a live backend (as the original 17 Sep recording did) but paced to stay
under 3 minutes: nine scenes, two role switches (credit officer → admin), no dwell time
wasted.

- **Real sign-in, twice.** Scene 1 signs in as `s.kulkarni` (credit officer, scoped to
  MSME-CC/MSME-TL/LAP by the server itself — confirmed on screen). Scene 8 signs out and
  back in as `a.deshmukh` (admin) to reach the audit log, which is admin-only
  (`RequireRole allow={['A']}` in `App.jsx`) — a credit officer cannot see it, honestly.
- **"Record action" is actually clicked.** A real `POST /drishti/account/{id}/action`
  write, appended to the hash-chained audit log under the signed-in user's own id —
  visible afterwards in "Actions recorded on this account" and, in scene 8, in the admin
  audit table itself.
- **The account used in the 17 Sep recording, MSME33100, is not in this published run**
  (the committed export samples ~710 of the book's 12,760 accounts for the individual-row
  screens; MSME33100 isn't in that sample, same limitation the 21 Sep static take
  documented). The hero account below, **MSME16350**, is in it and tells the same "not
  applicable" story a LAP account does (no revolving credit limit to draw on).
- **The validation table's "fail — accepted" rows are real**, not simulated: four
  pre-registered criteria (DR-12, DR-14, DR-18, DR-19) fail on this run and were accepted
  in advance (`app/services/validation.py`'s acceptance record, computed from
  `validation/report/report.json` and attached to the published run) — the screen colours
  them distinctly from a pass and from a still-blocking failure, and never as a pass.

---

**0:00–0:10 — Sign in, live**
> This is DRISHTi, signed in for real on a live backend — not a frozen demo bundle.

**0:10–0:24 — Watch-list: role-scoped**
> Sneha Kulkarni, credit officer, scoped to three portfolios by the server itself. Her
> watch-list: two hundred forty-five Red, four hundred fifty-eight Amber, of twelve
> thousand seven hundred sixty scored accounts.

**0:24–0:46 — Hero account: why this one**
> Why this account — MSME16350: a ninety-seven percent default probability, eighty days
> past due, flagged five months early. The channel strip is honest about what the bank
> can't see — four signals observed, ten read not collected, never a hidden zero.

**0:46–1:14 — Memo + a real recorded action**
> The auto-drafted memo recommends credit review, human review required. Recording what
> she did is a real, audited write — one click, hash-chained, and it cannot be edited or
> deleted afterward.

**1:14–1:34 — Portfolio risk**
> Portfolio risk, all eight products: Red-band precision from retail-unsecured's low
> seventies up to one hundred percent on the thinnest bands — each one carries its own
> interval.

**1:34–1:58 — Honesty headline**
> Switching to the admin view for the model's own report card: the honesty headline —
> eighty-eight point six percent of Red-flagged accounts went N-P-A within eight months,
> n equals two hundred forty-five, beside the sixteen point one percent this operating
> point still missed. That rise from eighty-four point five percent is the Red threshold
> moving up on a held-out policy fold — not the model improving.

**1:58–2:14 — Validation: fail — accepted**
> The validation table is honest about its own limits too: of twenty-six pre-registered
> criteria, four fail — and are accepted — named in advance, never hidden.

**2:14–2:36 — Audit trail (as admin)**
> And the evidence trail behind that one click: the append-only, hash-chained audit log,
> filtered to her — her action, on MSME16350, exactly as recorded.

**2:36–2:46 — Sign-off**
> What this supports: a rank-ordered, interval-bound signal on a published run — never a
> certified default. DRISHTi advises. The credit officer decides.

---

## What was verified on screen

The following was checked against the actual on-screen text for every relevant scene,
not just eyeballed:

- Watch-list: `Credit officer`, `3 portfolios`, `245`, `458`, `12,760`
- Hero account: `54%`, `80` (days past due), `5 mo before trouble`, `not applicable`
- Memo: `credit review`, `human review required`
- Portfolio risk: `100%` (thinnest bands)
- Model & Metrics: `88.6%`, `245`, `97.3%`, `16.1%`, `0.885` (AUC)
- Validation: `26`, `fail`, `accepted`
- Audit (admin): `MSME16350`, `audit`

Console stayed clear of errors too, net of two pre-registered, expected 401s (the app's
own `/auth/me` liveness probe before a session exists — the first cold load, and again
right after the admin sign-in's sign-out step) and a pre-existing, cosmetic React
dev-mode "missing key prop" warning in `AccountDetail.jsx`, not fixed as part of this
recording.

## What isn't confirmed on screen

- **The 84.5% → 88.6% comparison and its threshold-not-model explanation**, and the exact
  DR-12/DR-14/DR-18/DR-19 criterion ids. Both are documented, citable facts
  (`MODEL_CARD.md` §8; `validation/report/report.json`) and both really are on the Model &
  Metrics / Validation screens in this build, but only the headline numbers and the word
  "accepted" were checked against the screen, not the full prose or every individual
  criterion id rendered — narrated here as what a presenter reads over the screen, not
  claimed as verified word-for-word.
- **AUC 0.885's confidence interval, the exact Red/Amber thresholds, and the
  ecosystem/contagion panel.** All render correctly in this build (confirmed by eye while
  preparing this script) but were not checked against the screen or covered by this cut's
  narration — appendix exhibits, not this 3-minute tour.

## Superseded

Two earlier recordings are kept for reference: `docs/demo/drishti-demo-2026-09-17.mp4`
(≈3:46, the original live-backend take, MSME33100, the old 84.5%/n=283 numbers, now
stale) stays where it was. This file replaces the 21 Sep **static-demo** take as the
current demo video.
