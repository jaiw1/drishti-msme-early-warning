# DRISHTi — stale-string sweep (SB-1)

Swept: `README.md`, `MODEL_CARD.md`, `DATA_CARD.md`, `app/src/**` copy, `app/index.html`, the
deck (`DRISHTi — Prototype Submission Deck.pptx`). Patterns: `~0.95 AUC` / `0.95`, `93%` flagged
≥6 mo, `1.8%`, `9,000 imaginary`, `MSME loan` as the whole scope, `~2.7%/year`, `complements
SAJAG` / `SAJAG`, `90% accuracy` / `accuracy`, `10-month median lead`, vercel URLs presented as
the deployment.

Source of truth for every replacement: `validation/report/REPORT.md` +
`validation/report/report.json` (26 criteria graded, commit `0c92bf980c39`, generated
2026-09-17T02:36:16+05:30 — DM-8 round 2, the last permitted tuning round),
`app/public/demo_data.json` (`metrics.honesty`, `metrics.rank_order`, `thresholds`,
`portfolio_summary`, `ecosystem`), `MODEL_CARD.md` §8/§9/§13/§17. Headline: **"84.5% of
Red-flagged accounts went NPA within 8 months (95% CI 79.8%–88.2%, n=283)"** — read live from
`metrics.honesty.headline`, **not** the "80.7%" figure named in this lane's own task brief,
which predates DM-8 round 2's final regeneration. Always read the number fresh from the file;
never carry one forward from an earlier report.

Per the task split: I fixed every README and deck row myself (edits committed on `main`). Cards
(`MODEL_CARD.md`, `DATA_CARD.md`) are the model/data lanes' territory, not L12's — rows found
there are logged as "kept" (they narrate *retired* numbers on purpose, as history, or are
DATA_CARD's own already-correct disclosure of the same drift this sweep exists to catch) and are
not mine to edit. `app/src/**` rows are listed for L10; I did not edit `app/**`.

## README.md (FIXED — this lane)

| Line (before) | String | Replacement | Why |
|---|---|---|---|
| 1 | `# DRISHTi — MSME Loan Early-Warning System` | `# DRISHTi — Early-Warning System for IDBI's Lending Book` | scope was "MSME loan" only; the mandate is one model across all eight lending portfolios (MSME + retail: Housing, Education, Agri, Retail-Unsecured, LAP, Auto) |
| 7 | `Live demo: https://drishti-ews.vercel.app` | `Interim demo (pre-sandbox): https://drishti-ews.vercel.app` + note that the bank-sandbox deployment is not live as of this writing | vercel presented as *the* deployment |
| 22 | `9,000 imaginary businesses`, `≈2.7%/year — matching IDBI's real small-business default rate` | rewritten as "How it works" (population → shared latent stress → portfolio-specific channels), with the correct current annual base rate (3.63% label base rate / 3.31% slippage, `DR-04`/`DR-03`) | `9,000` was one of two shipped populations and no longer the one the demo actually reads (`demo_data.json` meta = 45,000×48 this round); `2.7%/year` conflated the 8-month base rate (2.72%) with the annual one (3.9%/3.63%) — flagged by `DATA_CARD.md`'s own "Research gaps" as drifted |
| 49 | `median of ~10 months`, `93% are flagged at least 6 months ahead` | `8 months` (median_first_warning_months), `79.7%` (pct_flagged_6mo_ahead) | both stale — `demo_data.json` → `metrics.median_first_warning_months`=8, `metrics.pct_flagged_6mo_ahead`=0.797, not 93% |
| 51 | `~87%` (top-10% recall) | `86.5%` (95% CI 82.5–89.7%) | `metrics.recall_at_10pct_budget`=0.8646 |
| 59 | `technical score ~0.95` | replaced with the full three-point AUC story: 0.947 July → 0.927 pre-noise → 0.902 shipped, inside the pre-registered [0.82, 0.92] | `~0.95` was the pre-noise-hardening number; the shipped, gated AUC is 0.902 (`MODEL_CARD.md` §13) |
| 64 | `cash-flow + overdraft-use drive ~81%... missed-payments just 1.8%` | `days-past-due family contributes just 3.8% of attribution at 10–12 months (primary reading, DR-15); alternative reading 20.9%` | `81%`/`1.8%` was round 1's 5-family taxonomy on an earlier fixture; round 2's 9-family DR-15 result is 3.81% primary / 20.92% alternative (`report.json` DR-15) |
| n/a | `90% accuracy` framing (headline) | replaced throughout with the honesty-block headline, raw accuracy vs. flag-nobody baseline, and `missed_npa_share` | this is exactly the mentor-rejected framing the whole card exists to retire; `export_demo.py::assert_honesty` also guards against it re-appearing |
| n/a | (implicit) "SAJAG" framing | not present in the stale README's prose, but the rewritten README states DRISHTi explicitly as standalone, per the mandate to drop "complements SAJAG" | mandate context (plan §Context) |

Also checked and **not present** in the stale README: `complements SAJAG` (not used there — it
was a deck-only phrase, see below), the bare word `accuracy` used approvingly (only appeared
inside the "why not accuracy" framing, which is correct usage and was kept/expanded).

## MODEL_CARD.md / DATA_CARD.md (model/data lanes' territory — logged, not edited)

| File:line | String | Status |
|---|---|---|
| `MODEL_CARD.md` §13 | `0.947 (July 2026)`, `0.927 (pre-noise-hardening checkpoint)` | **kept** — this is the AUC story itself, correctly framed as a historical sequence ending at the shipped 0.902, exactly the source this README's own AUC story draws from |
| `MODEL_CARD.md` §8 | `44.1% [35.4–53.1]` (9k, pre-round-2 headline) | **kept** — explicitly labelled "pre-round-2" in its own table, next to the current 84.5% (45k, round 2); correct as history |
| `DATA_CARD.md` "Research gaps" | `"Two README numbers drifted this week... 93%→89%... 1.8%→2.05-2.1%"` | **kept** — this is DATA_CARD's *own* disclosure of the drift this exact sweep is closing; it names an intermediate value (89%, 2.05-2.1%) from before DM-8 round 2's final regeneration, which is itself now superseded by the current `demo_data.json` (79.7%, 3.81%) — the README cites the current file, not this note, but the note is correctly framed as history and is not mine to edit |
| `DATA_CARD.md` §"What a jury will push on" item 5 | `"Real slippage is 0.63%; why does the model train on 3-5%?"` | **kept** — disclosure, not a stale claim |
| `DATA_CARD.md` §"Research gaps" (SD-D8 resolved item) | `"generate_data.py's own module docstring was stale (~2.7%/year slippage, MSME loan)"` | **kept** — this is DATA_CARD's own record that the *docstring* (not the README) was already fixed at SD-D8; matches this sweep's independent finding that the README's copy of the same numbers was still stale |

None of these needed a fix: every one is either explicitly historical or is itself the
disclosure record for the exact drift SB-1 exists to catch.

## app/src/** and app/index.html (for L10 — not edited, per instructions)

| File:line | String | Note |
|---|---|---|
| `app/index.html:7-9` | `MSME Loan Early-Warning`, `Track 4`, `AUC 0.81` | `MSME Loan` in the `<title>`/meta description understates scope the same way the old README did (§ above); `AUC 0.81` refers correctly to the *real-data* model, unaffected by DM-8. Flagging the title/meta scope wording for L10 to decide alongside any other `app/index.html` copy changes — out of this lane's edit rights (`app/**`). |
| `app/src/components/RealModel.jsx:32` | `Math.round((syntheticAuc \|\| 0.95) * 100) / 100` | the `0.95` here is a **fallback default**, not a stale display value — it only renders if `syntheticAuc` is unset. Not a bug, but a candidate for L10 to update the fallback to `0.90` so a data-load failure doesn't silently show a pre-round-2 number. |
| `app/src/test/fixtures/demo_data.min.json` | `"generated_from": "synthetic MSME loan panel (6,000 accounts x 36 months)..."`, `auc: 0.946`, `median_first_warning_months: 10` | this is a **test fixture** (a deliberately small, independent synthetic sample for unit tests), not app-facing copy — its numbers are not meant to match the shipped `demo_data.json` and don't need to change for this sweep. Noting for L10's awareness only. |
| `app/src/test/fixtures/api.js:186,201,254` | `red_band_precision_8m` test values (0.75, 0.924), `DR-05 ... expected 1.047` | mock API fixtures for frontend tests — intentionally synthetic test values, not display copy. No action needed. |
| `app/src/screens/*.jsx`, `help/screens.json`, `domain/shapes.test.js` | `"accuracy"` appearing in "why raw accuracy is meaningless" / "not_claimed: accuracy" framing | this is the **correct** usage the whole honesty mechanism exists to produce — these are guard tests and copy that *disown* accuracy, not claims of it. No action needed; flagging so L10 knows this copy is load-bearing and should stay green. |

No occurrences of `9,000 imaginary`, `complements SAJAG`, `93%`, `1.8%`, or vercel-as-deployment
were found in `app/src/**`.

## Deck — `DRISHTi — Prototype Submission Deck.pptx` (FIXED — this lane, SB-3)

26 text-run edits across slides 2, 3, 4, 5, 6, 7, 8, 11, 12 — the full before/after list is in
the SB-3 patch script
(`/private/tmp/.../scratchpad/patch_drishti_deck.py`, applied and then two follow-up
runs on slide 12/shape 137 to avoid duplicating slide 12/shape 133's "swap the synthetic panel"
bullet). Summary of what changed: `10 mo` → `8 mo`; `93%` → `79.7%`; `87%` → `86.5%`; `81% /
1.8%` leakage line → `3.8% / 20.9%` (DR-15); `9,000 × 36 months` → `45,000 × 48 months, 8
portfolios`; `AUC 0.947` synthetic-panel box → the full `0.947 → 0.927 → 0.902` story;
`Brier 0.010` → `0.014`; network-contagion counts `433 / 17 / ₹99.7cr` → `1,689 / 61 / ₹209cr`
(`ecosystem` in `demo_data.json` had also drifted, not just the five named patterns); `"90%
accuracy"` footer → the honest "flagging nobody scores 97.3%" framing; both `Complements IDBI's
SAJAG EWS` (slide 3) and the `SAJAG` integration bullet (slide 12) and the `& SAJAG` API list
entry (slide 8) removed per the mandate to drop that framing; the "no server, no database"
architecture claim (slide 7) replaced with an honest note that a real backend
(`rrsquad-platform`) is being built this week; vercel links on slides 2 and 6 reframed as
"interim, pre-sandbox demo," not the deployment. Backup taken before editing:
`DRISHTi — Prototype Submission Deck.backup-2026-09-17.pptx` (beside the original, outside the
repo). Slide 1 (`Track 4 — Default Prediction Model (predict MSME loan default 12 months in
advance)`) was left untouched — it is the portal's own required Team-Details/Problem-Statement
field, not a claim this lane edits (same treatment SANKET's equivalent SB-3 gave its Slide 1).

## Out of this lane's scope (flagged, not touched)

`../DEMO-VIDEO-SCRIPT.md` (three rows in the stale-string inventory: `drishti-ews.vercel.app`
×3, `Track 4`, `0.81` kept) lives outside this repo, in `IDBI Innovate/` root, and is neither
the deck nor `README.md`/`docs/**` — it is SB-5/SB-6's ("rewrite `sanket-autopilot.mjs`... clone
to `drishti-autopilot.mjs`") territory per plan §B/L12, not this lane's to edit. Its `0.81` row
is already correctly marked "keep — still true" in the inventory; the three vercel-URL rows
should get the same "interim demo" reframing this lane gave the README and deck, whenever SB-5/6
touches that file.

## Known follow-up (not mine to fix, flagging for the record)

Slides 2, 6 and 10 embed **screenshots** of the live app (Picture 64 on slide 2; Picture 90 and
Picture 92 on slide 6; the four snapshots on slide 10) that still show pre-DM-8 numbers baked
into the pixels — visibly, on slide 6's screenshots: `2,543 live accounts`, `10 mo`, `93%
flagged ≥6 months ahead`, and a `27%` example score. These are images, not text runs — SB-3's
mandate is text runs plus swapping a *chart* PNG rendered from `demo_data.json`/`report.json`;
these are full app screenshots of the deployed cockpit, which is SB-4's job ("final
screenshots"), not SB-1/SB-3's. Recapturing them requires driving the live app, out of this
lane's budget (no model runs, no browser automation set up here). **Slides needing SB-4
screenshots: 2, 6, 10.**
