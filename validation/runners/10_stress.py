"""
10 Stress — a downturn, and no bureau

Pre-registered criteria this runner answers: DR-22, DR-23

Consumes
--------
* `validation.runners._refit.baseline` — the small-book (9,000 x 36, seed 7)
  grouped-holdout fit, shared with runner 08's ablation baseline and runner
  09's seed-7 iteration (same `_shared.py` cache key — computed once).
* `validation.runners._refit.fit_reweighted` — a fresh fit with eligible
  training-split positives duplicated (2x base rate).
* `validation.runners._refit.score_bureau_masked` — the baseline model
  RE-SCORED with the Bureau family blanked to NaN at test time (no refit).

Produces
--------
* `figures/stress_auc_deltas.png`
* DR-22 (|ΔAUC| under 2x base rate, <= 0.03), DR-23 (|ΔAUC| under bureau-
  missing, <= 0.02).

Method, as pre-registered
--------------------------
Two pre-registered scenarios against the base (small-book) run:
  (a) base rate doubled — eligible training-split positive rows duplicated
      once more before refitting, scored against the SAME (unduplicated)
      test split as the baseline, so the comparison is apples-to-apples;
  (b) the bureau family fully masked AT SCORE TIME (100% missing, not the
      ~7% MAR missingness the generator already builds into the base
      scenario — criteria.yaml DR-23's own note) — the ALREADY-fitted
      baseline model re-scored with `bureau_score` blanked to NaN, since
      LightGBM routes NaN through its learned missing-value branch.
Both report the absolute AUC change, with direction, against the small-book
baseline (NOT the 45,000 x 48 DR-01 holdout — see `_refit.py`'s module
docstring for why these four runners use the small book throughout).
"""

from __future__ import annotations

import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _refit as rf
from . import _shared as sh

INPUTS: tuple[str, ...] = ("data/msme_loan_panel.csv", "data/accounts_static.csv")

SEED = 7  # matches rigor.py / export_demo.py's own random_state; shared with 08/09's seed-7 fit


def _delta_ci(ctx: RunnerContext, df_test: pd.DataFrame, y_test, p_base, p_stress, seed: int) -> tuple[float, float]:
    boot_df = pd.DataFrame({
        "account_id": df_test["account_id"].to_numpy(),
        "y": y_test, "p_base": p_base, "p_stress": p_stress,
    })
    return sh.bootstrap_ci(
        boot_df,
        lambda d: sh.grouped_auc(d["y"].to_numpy(), d["p_stress"].to_numpy())
        - sh.grouped_auc(d["y"].to_numpy(), d["p_base"].to_numpy()),
        n=sh.n_boot(ctx), seed=seed,
    )


def _figure(ctx: RunnerContext, baseline_auc: float, scenarios: dict[str, float]) -> str:
    import matplotlib.pyplot as plt

    labels = ["base (9k book)"] + list(scenarios)
    values = [baseline_auc] + list(scenarios.values())
    colors = ["#1f6feb"] + ["#da3633"] * len(scenarios)
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(labels, values, color=colors)
    ax.set_ylim(0.5, 1.0)
    ax.set_ylabel("AUC")
    ax.set_title("DR-22/DR-23 — stress scenarios vs base AUC")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right", fontsize=8)
    return sh.savefig(fig, ctx, "stress_auc_deltas.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if not ({"DR-22", "DR-23"} & set(by_id)):
        return []

    base = rf.baseline(ctx, SEED)
    baseline_auc = sh.grouped_auc(base["y_test"], base["p_test"])
    df_test = base["df_test"]
    results: list[Result] = []

    scenarios_for_fig: dict[str, float] = {}

    if "DR-22" in by_id:
        stress = rf.fit_reweighted(ctx, SEED, multiplier=2)
        stress_auc = sh.grouped_auc(stress["y_test"], stress["p_test"])
        delta = abs(stress_auc - baseline_auc) if (stress_auc is not None and baseline_auc is not None) else None
        ci = _delta_ci(ctx, df_test, base["y_test"], base["p_test"], stress["p_test"], SEED) if delta is not None else None
        scenarios_for_fig["2x base rate"] = stress_auc
        direction = "up" if (stress_auc or 0) > (baseline_auc or 0) else "down"
        results.append(Result(
            "DR-22", value=round(delta, 4) if delta is not None else None, ci=ci, n=stress["n"],
            detail=(f"base AUC={round(baseline_auc, 4)}, 2x-base-rate AUC={round(stress_auc, 4)} "
                    f"({direction}), |ΔAUC|={round(delta, 4) if delta is not None else None}. "
                    f"{stress['n_extra']} extra duplicated positive training rows (multiplier=2), "
                    f"scored against the unduplicated test split."),
        ))

    if "DR-23" in by_id:
        masked = rf.score_bureau_masked(ctx, SEED)
        masked_auc = sh.grouped_auc(masked["y_test"], masked["p_test"])
        delta = abs(masked_auc - baseline_auc) if (masked_auc is not None and baseline_auc is not None) else None
        ci = _delta_ci(ctx, df_test, base["y_test"], base["p_test"], masked["p_test"], SEED) if delta is not None else None
        scenarios_for_fig["bureau fully missing"] = masked_auc
        direction = "up" if (masked_auc or 0) > (baseline_auc or 0) else "down"
        results.append(Result(
            "DR-23", value=round(delta, 4) if delta is not None else None, ci=ci, n=masked["n"],
            detail=(f"base AUC={round(baseline_auc, 4)}, bureau-masked AUC={round(masked_auc, 4)} "
                    f"({direction}), |ΔAUC|={round(delta, 4) if delta is not None else None}. "
                    f"Bureau family ({masked['bureau_cols']}) blanked to NaN at score time on the "
                    f"ALREADY-fitted model (100% missing — not the generator's baseline ~7% MAR "
                    f"missingness, per criteria.yaml DR-23's note)."),
        ))

    if scenarios_for_fig:
        fig = _figure(ctx, baseline_auc, scenarios_for_fig)
        for r in results:
            r.figures.append(fig)

    return results
