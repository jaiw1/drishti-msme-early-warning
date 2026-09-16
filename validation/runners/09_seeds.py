"""
09 Seed sweep — is the headline a property of the model or of the seed

Pre-registered criteria this runner answers: DR-20, DR-21

Consumes
--------
* `validation.runners._refit.baseline` — one small-book (9,000 x 36) grouped-
  holdout fit per registered seed (`criteria.yaml seeds.list`: [7, 8, 9, 10,
  11]). Each call is `_shared.get_holdout` under a `RunnerContext` pointed at
  that seed's 9,000 x 36 panel — the SAME small-book convention `_refit.py`
  documents for runners 07/08/10, so a seed already generated for the
  ablation baseline (seed 7) or the permutation cross-check is never
  regenerated here.

Produces
--------
* `figures/seed_sweep_auc.png`
* DR-20 (how many registered seeds actually ran — must be >= 5), DR-21
  (width of the cross-seed 2.5th-97.5th percentile interval of the per-seed
  AUC point estimates — must be <= 0.02, per `criteria.yaml confidence.
  cross_seed`).

Method, as pre-registered
--------------------------
Re-run generation, the grouped 70/30 split and the fit across every
registered seed, and report the per-seed AUCs, their cross-seed percentile
interval and its width. Every seed that ran appears in the per-seed
breakdown in `detail` (never in `Result.breakdown` itself — DR-20/DR-21 are
BOTH `scope: overall`, and the harness's `grade()` grades every cell of a
non-empty `breakdown` against the SAME band; a per-seed AUC and a CI-width
criterion are not the same quantity, so putting the per-seed table in
`breakdown` would silently mis-grade it).
"""

from __future__ import annotations

import numpy as np

from validation.criteria import Criterion, Result, RunnerContext
from . import _refit as rf
from . import _shared as sh

INPUTS: tuple[str, ...] = ("data/msme_loan_panel.csv",)


def _figure(ctx: RunnerContext, per_seed: list[dict], lo: float, hi: float) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    seeds = [r["seed"] for r in per_seed]
    aucs = [r["auc"] for r in per_seed]
    ax.bar([str(s) for s in seeds], aucs, color="#1f6feb")
    ax.axhspan(lo, hi, color="#2ea043", alpha=0.15, label=f"cross-seed 95% interval [{lo:.4f}, {hi:.4f}]")
    ax.set_xlabel("seed")
    ax.set_ylabel("grouped holdout AUC (9,000 x 36 book)")
    ax.set_title(f"DR-20/DR-21 — AUC across {len(seeds)} seeds (width {hi-lo:.4f})")
    ax.legend(fontsize=8)
    return sh.savefig(fig, ctx, "seed_sweep_auc.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if not ({"DR-20", "DR-21"} & set(by_id)):
        return []

    seeds = list(ctx.seeds) if ctx.seeds else [7, 8, 9, 10, 11]
    per_seed = []
    for s in seeds:
        h = rf.baseline(ctx, s)
        auc = sh.grouped_auc(h["y_test"], h["p_test"])
        per_seed.append(dict(seed=s, auc=round(auc, 4) if auc is not None else None, n=len(h["y_test"])))

    valid = [r["auc"] for r in per_seed if r["auc"] is not None]
    n_run = len(valid)
    results: list[Result] = []

    lo = hi = width = None
    if valid:
        lo, hi = (float(x) for x in np.percentile(valid, [2.5, 97.5]))
        width = round(hi - lo, 4)

    fig = None
    if valid:
        fig = _figure(ctx, per_seed, lo, hi)

    if "DR-20" in by_id:
        results.append(Result(
            "DR-20", value=n_run, n=n_run, figures=[fig] if fig else [],
            detail=f"seeds actually run: {seeds} ({n_run}/{len(seeds)} produced a valid AUC). Per-seed: {per_seed}.",
        ))

    if "DR-21" in by_id:
        results.append(Result(
            "DR-21", value=width, ci=(round(lo, 4), round(hi, 4)) if lo is not None else None,
            n=per_seed[0]["n"] if per_seed else None, figures=[fig] if fig else [],
            detail=(f"cross-seed 2.5th-97.5th percentile interval of the {n_run} per-seed AUC point "
                    f"estimates (criteria.yaml confidence.cross_seed), width={width}. Per-seed: {per_seed}. "
                    f"Note: at n={n_run} seeds the percentile interval is close to (min, max) rather than "
                    f"a smooth tail estimate — reported as pre-registered, not smoothed."),
        ))

    return results
