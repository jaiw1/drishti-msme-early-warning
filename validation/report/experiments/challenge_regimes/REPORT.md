# E5 — the shipped model on regimes it was never fitted to

**Question.** How does the SHIPPED model behave on generator regimes it was never fitted to, with nothing retuned afterwards?

**Model seed** 7 (frozen in the artefact) · **development generator seed** 20260709 · every regime below uses a different generator seed.  
**Panel** 9,000 accounts × 36 months each.  
**Operating point** amber 0.069298 / red 0.343723, frozen.  

**No generator parameter was adjusted after seeing any result below, and no threshold was re-derived. The artefact is the one the cockpit ships.**

## Read the control first

Three `unseen_seed*` rows change the generator seed and nothing else. The range they
span IS the noise floor: a regime that moves a metric no further than three identical
panels move it among themselves has demonstrated nothing. **Bold** marks a value that
falls outside the controls' own range — a weak claim, and the strongest one three
replicates entitle anyone to make. Deltas are against the first control.

| regime | mechanism | base rate | AUC | ΔAUC | Red n | Red precision | missed NPA | flagged | ECE |
|---|---|---|---|---|---|---|---|---|---|
| **unseen_seed** (control) | generator seed only | 3.25% | 0.8657 | — | 155 | 82.6% [76%–88%] | 19.5% | 6.1% | 0.0043 |
| unseen_seed_b | generator seed only (control replicate) | 3.62% | 0.8631 | — | 162 | 85.2% [79%–90%] | 19.0% | 6.0% | 0.0055 |
| unseen_seed_c | generator seed only (control replicate) | 3.77% | 0.8709 | — | 175 | 85.7% [80%–90%] | 17.0% | 5.7% | 0.0059 |
| base_rate_up | risk_intercept -2.35 -> -1.75 | 5.74% | 0.8683 | +0.0026 | 250 | **87.2% [82%–91%]** | **16.2%** | **7.4%** | 0.0199 |
| base_rate_down | risk_intercept -2.35 -> -3.05 | 1.96% | 0.8761 | **+0.0104** | 99 | **74.8% [65%–82%]** | **9.8%** | **4.7%** | 0.0062 |
| noisier_borrowers | risk_noise_sd 1.15 -> 1.60 | 4.03% | 0.8707 | +0.0050 | 186 | 84.4% [79%–89%] | **14.9%** | **6.5%** | 0.0072 |
| heavy_missingness | statement_gap_share 0.080 -> 0.240 | 3.57% | 0.875 | **+0.0093** | 160 | 84.4% [78%–89%] | **14.5%** | **5.6%** | 0.0046 |
| stale_sources | bureau lag +3 months, refresh interval doubled | 3.72% | 0.8659 | +0.0002 | 160 | **89.4% [84%–93%]** | **16.9%** | 5.8% | 0.0066 |
| more_silent_defaults | silent_book_share 0.080 -> 0.160 | 3.77% | 0.8785 | **+0.0128** | 173 | **86.1% [80%–90%]** | **16.3%** | 5.8% | 0.0056 |
| abrupt_onset | onset_mean 13 -> 7, onset_bounds (5,18) -> (3,10) | 3.49% | 0.7709 | **-0.0948** | 101 | **78.2% [69%–85%]** | **41.4%** | **5.1%** | 0.0099 |
| macro_shock | risk_intercept -1.75 + abrupt onset + 3x statement gaps, together | 5.79% | 0.7548 | **-0.1109** | 146 | **87.0% [81%–92%]** | **35.0%** | 5.8% | 0.0296 |

## What this found

**The model is robust to most of what was varied.** Base rate, borrower noise, three times the statement gaps, staler bureau data and twice the silent-default share all leave AUC between 0.863 and 0.878 — the controls alone span 0.8631–0.8709, so most of those moves are not readable.

**Two regimes break it, and they are the same mechanism.** `abrupt_onset` (AUC 0.7709) and `macro_shock` (AUC 0.7548) both halve the time stress takes to develop. Missed-NPA share more than doubles, from 20% in the control to 41%. An early-warning model reads a deterioration TRAJECTORY through a four-month trailing mean; a borrower who goes from healthy to NPA inside that window cannot be warned about, and no threshold choice repairs it.

**Both of those AUCs fall below the pre-registered DR-01 floor of 0.82.** DR-01 grades the development panel and is unaffected — but it is worth stating plainly that the shipped model, unretuned, would not clear its own acceptance band on a book whose stress arrives quickly. That is a limitation of the product, not a failure of the experiment.

**Rarity hurts precision even when ranking is intact.** `base_rate_down` has the HIGHEST AUC here (0.8761) and the LOWEST Red precision (74.8%). A fixed threshold on a book with half the defaults flags a band that is proportionally more false positives. A bank whose book is cleaner than this simulator's should expect the published precision to fall, and should re-derive its operating point rather than inherit ours.

## Why each regime is here

**`unseen_seed`** — generator seed only (generator seed 20260931).  
the control: how much does a metric move when NOTHING but the seed changes? A regime that moves a number less than this has shown nothing.

**`unseen_seed_b`** — generator seed only (control replicate) (generator seed 20260941).  
a second control. One control gives a point; three give a BAND, and without that band no single-seed regime difference below is readable.

**`unseen_seed_c`** — generator seed only (control replicate) (generator seed 20260942).  
a third control, for the same reason.

**`base_rate_up`** — risk_intercept -2.35 -> -1.75 (generator seed 20260932).  
a materially worse book. Base rate is the first thing that differs between a simulator and a real portfolio, and between one bank's book and another's.

**`base_rate_down`** — risk_intercept -2.35 -> -3.05 (generator seed 20260933).  
a benign book. Rarity is its own difficulty: precision falls when positives are scarce even if ranking is unchanged.

**`noisier_borrowers`** — risk_noise_sd 1.15 -> 1.60 (generator seed 20260934).  
weaker signal-to-noise in who eventually defaults — the irreducible-randomness term the development generator was tuned against.

**`heavy_missingness`** — statement_gap_share 0.080 -> 0.240 (generator seed 20260935).  
three times the statement-feed gaps. A real extract is patchier than a simulator's, and the model must degrade gracefully rather than cliff.

**`stale_sources`** — bureau lag +3 months, refresh interval doubled (generator seed 20260936).  
source latency: the bureau score the bank carries is older and refreshed less often than the development panel assumes.

**`more_silent_defaults`** — silent_book_share 0.080 -> 0.160 (generator seed 20260937).  
twice the share of defaults that arrive with no warning chain at all. This is the population an early-warning model is structurally unable to catch, and the honest question is how fast recall falls as it grows.

**`abrupt_onset`** — onset_mean 13 -> 7, onset_bounds (5,18) -> (3,10) (generator seed 20260938).  
stress that develops in half the time. Lead time is the product's whole claim, so a book that deteriorates abruptly is its hardest case.

**`macro_shock`** — risk_intercept -1.75 + abrupt onset + 3x statement gaps, together (generator seed 20260939).  
a compound downturn: more borrowers go bad, they go bad faster, and the data feed degrades at the same time — which is what actually happens in a shock.

## Simulated cost at the frozen operating point

Marked as simulation results, per the review. These are **not** projected bank
savings: every cost parameter is an ASSUMPTION (`src/costs.py`), the books are
synthetic, and each regime is deliberately outside the development setting. They are
comparable to each other and to nothing else.

| regime | expected cost (₹ cr) | per account (₹) |
|---|---|---|
| unseen_seed | 7.31 | 8,557 |
| unseen_seed_b | 5.30 | 6,230 |
| unseen_seed_c | 8.87 | 10,462 |
| base_rate_up | 13.08 | 15,902 |
| base_rate_down | 5.18 | 5,945 |
| noisier_borrowers | 6.96 | 8,246 |
| heavy_missingness | 5.41 | 6,368 |
| stale_sources | 8.66 | 10,205 |
| more_silent_defaults | 6.98 | 8,243 |
| abrupt_onset | 7.49 | 8,795 |
| macro_shock | 10.86 | 13,253 |

_Not a projected bank saving. Every cost parameter is an ASSUMPTION (src/costs.py PARAM_NOTES); the book is synthetic; and the regime's own parameters are deliberately outside the development setting. Compare regimes to each other, never read the absolute figure as rupees the bank would keep._
