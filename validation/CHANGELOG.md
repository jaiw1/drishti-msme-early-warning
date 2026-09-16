# Changelog — DRISHTi validation pack

## 2026-09-16 — Pre-registered before first model run.

26 acceptance criteria registered across the twelve runners, transcribed from
the approved build plan (§B lane L8, §D gates G2 and G7), **before any DRISHTi
model result existed**. Nine cuts, both splits, the seed policy and the
confidence-interval method fixed at the same time. Runners are documented stubs;
they report `pending`, never `pass`.

One clarification was issued during registration and is recorded in
`criteria.yaml` under `rulings:` — the portfolio count is eight, not the seven
the plan text carried over from v1. It changes no threshold, only the number of
cells each per-portfolio criterion must clear.

Notable registered positions, all taken before results:

- `DR-01` grouped AUC floor **0.82, deliberately lowered from 0.85**, with a
  ceiling of 0.92.
- `DR-02` Red-band precision — the honest replacement for "90% accuracy" —
  registered with **no target**.
- `DR-24`/`DR-25` fairness reported, not gated.
