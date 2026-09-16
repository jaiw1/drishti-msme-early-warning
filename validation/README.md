# DRISHTi — validation pack

The acceptance criteria for the DRISHTi early-warning model, the harness that
checks them, and the report a bank model-risk reviewer reads.

```
validation/
  criteria.yaml   the contract: 26 pre-registered bands, 9 cuts, splits, seeds
  criteria.py     schema + loader (pydantic v2) and the runner contract
  run.py          discovery, execution, grading, exit code
  report.py       REPORT.md + report.json + figures/
  runners/        01_holdout … 12_baseline_ladder
  tests/          tests for the contract itself
  Makefile        make -C validation validate
  report/         generated output — gitignored, never committed by hand
```

## The principle: pre-registration

**`criteria.yaml` is committed before the first model result exists.** That
commit's git timestamp is the evidence. It is the only thing that distinguishes
"our model clears an AUC of 0.84" from "we decided 0.84 was the bar once we saw
0.84", and the two claims are worth very different amounts to a reviewer.

Three practices follow from it, and they are the whole point of this directory:

1. **Bands are written down before results, not after.** Every criterion carries
   a `source:` pointing at the clause of the build plan it came from, so a
   reviewer can check the transcription rather than trust it.
2. **Criteria may be added, never loosened.** See "Changing a criterion" below.
3. **Where a band was ambiguous, the interpretation is recorded in the file**, in
   that criterion's `note:` — at registration time, while we still did not know
   which reading would flatter us.

A concrete example, because it is the one a reviewer will probe: **the AUC floor
is 0.82, not 0.85** (criterion `DR-01`). It was deliberately lowered. A floor of
0.85 would have created pressure to tune the synthetic generator toward
separability until the data was easier than reality; published bank early-warning
models land around 0.81, so 0.82 is a floor that sits credibly beside the real
thing. The band also has a **ceiling of 0.92** — a synthetic panel scoring above
that has leaked its own generative structure, and the ceiling exists to catch
exactly that.

For the same reason, the headline number the mentors asked us to stop overselling
— Red-band precision, the honest replacement for "90% accuracy" — is registered
with **no target at all** (`DR-02`, `severity: report`). Putting a target on the
number that goes in the deck is the failure mode the whole pack exists to prevent.

## Running it

```bash
make -C validation validate          # run everything, write the report
make -C validation validate-strict   # the G7 gate form: pending and warn also fail
make -C validation criteria-test     # check the contract itself
make -C validation list              # print the bands without running anything
make -C validation deps              # pydantic v2, PyYAML, pytest
```

Equivalently, from the repository root:

```bash
python3 -m validation.run --criteria validation/criteria.yaml --out validation/report/
```

Useful flags: `--runner 03_by_cut` (repeatable) to run one runner; `--strict` for
the gate form; `--list` to dump the registered bands and exit.

Requires Python 3.12, `pydantic>=2`, `PyYAML`. The runners themselves will need
the pipeline's own dependencies (pandas, numpy, scikit-learn, lightgbm), which
the repo already has.

**Exit codes:** `0` no `fail` criterion failed · `1` at least one did (or, under
`--strict`, something is pending or warned) · `2` `criteria.yaml` would not load.
The deploy pipeline's verify step and gate G7 read the exit code; a model run
that fails verification stays `candidate` and never replaces the active run.

## Reading the report

`make validate` writes three things into `validation/report/`:

- **`REPORT.md`** — for humans. Leads with the verdict and the pre-registration
  statement (including when `criteria.yaml` actually entered git), then
  **failures first**, then pending criteria, then every criterion by runner with
  its band beside its observed value, then the registered rationale for each band
  in prose. Per-cut criteria carry a collapsible per-cell breakdown.
- **`report.json`** — the machine-readable twin. Read by the deploy verify step
  and open on screen during the G5 honesty gate, where every number in the README
  and the deck has to trace back to a row in it.
- **`figures/`** — plots the runners emit; each is named in its criterion's
  result so a figure can always be traced to the band it illustrates.

Statuses, in the order they matter:

| Status | Means |
|---|---|
| `fail` | the band was not met, and the criterion gates |
| `error` | the runner raised — treated as a failure |
| `warn` | the band was not met, and the criterion does not gate |
| `pending` | no result yet. **Not a pass.** `--strict` fails on it |
| `skipped_low_n` | the cell had fewer rows than the pre-registered `min_n`. Reported with its n, never silently dropped |
| `report` | no comparison is made; the value is recorded for a human to read |
| `pass` | the band was met |

`pending` is the one to watch today: the runners are stubs, so a plain
`make validate` currently exits 0 with every criterion pending. That is not a
pass, and `validate-strict` — the form gate G7 uses — correctly exits non-zero.

## Adding a criterion

1. Append an entry to `criteria:` in `criteria.yaml` with a **new** id
   (`DR-NN`), a `runner` from the twelve, a `metric`, a `scope`, an `op` and
   `threshold`, a `min_n`, a `severity`, a `rationale` and a `source`. Add a
   `note:` if the band needs interpreting.
2. Run `make -C validation criteria-test`. The schema rejects duplicate ids,
   unknown runners, non-numeric thresholds, inverted `between` bounds, and a
   `per_cut` criterion naming a cut that is not declared.
3. Teach the relevant runner to emit a `Result` for the new id. Runners measure;
   they never set `status` — the harness grades, so no runner can pass itself.

**The rule: criteria may only be ADDED after registration, never loosened.**
Adding a band makes the pack stricter, which no reviewer objects to. Widening
one, lowering a floor, raising a ceiling, changing `fail` to `report`, or raising
a `min_n` to exempt an inconvenient cell all weaken a claim that was already made,
and doing that quietly is indistinguishable from fitting the bar to the result.

If a band genuinely must change, it requires an `amendments:` entry at the foot
of `criteria.yaml`:

```yaml
amendments:
  - at: "2026-09-24T18:40:00+05:30"
    by: "RR Squad"
    criteria: ["DR-18"]
    change: "Cash-flow ablation floor 0.04 -> 0.03."
    rationale: >-
      Why, in terms a bank reviewer would accept. "It was failing" is not a
      rationale.
    loosening: true
```

`loosening: true` is not decoration: `REPORT.md` prints amendments in the
pre-registration section, and a loosening is flagged there for the reviewer.

Clarifications that do not change a band — resolving an ambiguity, correcting a
count — go in `rulings:` instead, with their own timestamp. There is one already:
the portfolio count, corrected from 7 to 8 on 16 Sep before any result existed.

## Writing a runner

Replace the stub in `runners/`. The contract is one function:

```python
def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]: ...
```

Each stub's docstring already names the files and columns it will consume and the
figures it will produce. Set `value`, `ci`, `n` — and `breakdown` (one dict per
cell, with `level`, `value`, `ci`, `n`) for a per-cut, per-portfolio or
per-product criterion. Leave `status` alone. A runner that stays silent about one
of its criteria leaves it `pending`; it cannot accidentally pass.

Bootstrap at the group level (`account_id`) — the panel has repeated measures and
a row-level bootstrap would report intervals that are far too tight.
