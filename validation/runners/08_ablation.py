"""
08 Ablation — which feature families actually carry the model

Pre-registered criteria this runner answers: DR-18, DR-19

Consumes
--------
* `validation.runners._refit.baseline` / `fit_dropping` — the small-book
  (9,000 x 36, seed 7) grouped-holdout fit, refit once per family in
  `src/rigor.py GROUPS` with that family's columns removed from BOTH fit and
  score. Seed 7 matches the "value already used in today's pipelines"
  convention (`criteria.yaml seeds.policy`) and is also `rigor.py`'s /
  `export_demo.py`'s own `random_state`.

Produces
--------
* `figures/ablation_deltas.png`
* DR-18: AUC drop when the cash-flow family (`GROUPS["Cash-flow (inflows /
  GST)"]`) is removed. DR-19: the largest AUC GAIN produced by dropping ANY
  family (must not exceed zero).

Method, as pre-registered
--------------------------
Refit with each of the nine families removed in turn and record the change in
grouped holdout AUC. Because `GroupShuffleSplit` depends only on
`(n_samples, groups, random_state)` — never on feature values — every
family-dropped fit shares the EXACT same train/test row split as the
baseline, so `baseline_p_test` and `dropped_p_test` line up row-for-row and a
delta can be pair-bootstrapped (resampling once, reusing the same resampled
rows against both prediction arrays) rather than needing two independent,
wider CIs.

Two registered readings: DR-18 is the cash-flow family's drop; DR-19 is the
largest AUC GAIN from dropping any family, registered at a hard 0.0 ceiling
with "no noise allowance" (`criteria.yaml` DR-19's own note) — so a small
positive delta inside its own CI is still recorded as a failure, not waved
through.

Per SD-D4/D5's own quick diagnostic, DR-18 is expected to come in well under
the 0.04 floor (~0.019) on this synthetic book; that is reported honestly, not
adjusted for.
"""

from __future__ import annotations

import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _refit as rf
from . import _shared as sh

INPUTS: tuple[str, ...] = ("data/msme_loan_panel.csv",)

SEED = 7  # matches rigor.py / export_demo.py's own random_state


def _delta_ci(ctx: RunnerContext, df_test: pd.DataFrame, y_test, p_base, p_drop, seed: int) -> tuple[float, float]:
    boot_df = pd.DataFrame({
        "account_id": df_test["account_id"].to_numpy(),
        "y": y_test, "p_base": p_base, "p_drop": p_drop,
    })
    return sh.bootstrap_ci(
        boot_df,
        lambda d: sh.grouped_auc(d["y"].to_numpy(), d["p_base"].to_numpy())
        - sh.grouped_auc(d["y"].to_numpy(), d["p_drop"].to_numpy()),
        n=sh.n_boot(ctx), seed=seed,
    )


def _figure(ctx: RunnerContext, deltas: dict[str, dict], cashflow_floor: float) -> str:
    import matplotlib.pyplot as plt

    fams = sorted(deltas, key=lambda f: deltas[f]["delta"])
    values = [deltas[f]["delta"] for f in fams]
    colors = ["#da3633" if v < 0 else "#2ea043" for v in values]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(fams, values, color=colors)
    ax.axvline(0.0, color="#8b949e", lw=1)
    ax.axvline(cashflow_floor, color="#1f6feb", ls="--", lw=1,
               label=f"DR-18 cash-flow floor {cashflow_floor}")
    ax.set_xlabel("ΔAUC (baseline − family-dropped): positive = family mattered")
    ax.set_title("DR-18/DR-19 — AUC delta by dropped family (9,000 x 36 book)")
    ax.legend(fontsize=8, loc="lower right")
    return sh.savefig(fig, ctx, "ablation_deltas.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if not ({"DR-18", "DR-19"} & set(by_id)):
        return []

    base = rf.baseline(ctx, SEED)  # calls sh.load_panel -> _ensure_src_on_path first
    import rigor

    baseline_auc = sh.grouped_auc(base["y_test"], base["p_test"])
    df_test = base["df_test"]

    deltas: dict[str, dict] = {}
    for fam in sorted(rigor.GROUPS):
        drop_cols = [c for c in rigor.GROUPS[fam] if c in base["cols"]]
        dropped = rf.fit_dropping(ctx, SEED, drop_cols)
        delta = baseline_auc - dropped["auc"] if (baseline_auc is not None and dropped["auc"] is not None) else None
        ci = _delta_ci(ctx, df_test, base["y_test"], base["p_test"], dropped["p_test"], SEED) if delta is not None else None
        deltas[fam] = dict(delta=round(delta, 4) if delta is not None else None, ci=ci,
                            dropped_auc=round(dropped["auc"], 4) if dropped["auc"] is not None else None,
                            n_cols=len(drop_cols), n=dropped["n"])

    cashflow_floor = float(by_id["DR-18"].threshold) if "DR-18" in by_id else 0.04
    fig = _figure(ctx, deltas, cashflow_floor)
    table_str = "; ".join(f"{f}: ΔAUC={d['delta']} (CI {d['ci']}, n_cols={d['n_cols']})"
                           for f, d in sorted(deltas.items(), key=lambda kv: -(kv[1]["delta"] or 0)))

    results: list[Result] = []

    if "DR-18" in by_id:
        cf = deltas.get("Cash-flow (inflows / GST)")
        results.append(Result(
            "DR-18", value=cf["delta"] if cf else None, ci=cf["ci"] if cf else None,
            n=cf["n"] if cf else None, figures=[fig],
            detail=(f"AUC drop when the Cash-flow (inflows / GST) family "
                    f"({cf['n_cols'] if cf else '?'} columns) is removed, on the 9,000 x 36 book "
                    f"(seed {SEED}), baseline AUC={round(baseline_auc, 4) if baseline_auc is not None else None}, "
                    f"dropped AUC={cf['dropped_auc'] if cf else None}. Full family table: {table_str}."),
        ))

    if "DR-19" in by_id:
        gains = {f: (round((-d["delta"]), 4) if d["delta"] is not None else None) for f, d in deltas.items()}
        valid = {f: g for f, g in gains.items() if g is not None}
        binding = max(valid, key=lambda f: valid[f]) if valid else None
        max_gain = valid[binding] if binding else None
        binding_ci = None
        if binding is not None and deltas[binding]["ci"] is not None:
            lo, hi = deltas[binding]["ci"]
            binding_ci = (round(-hi, 4), round(-lo, 4))  # gain = -delta, so CI flips and swaps
        results.append(Result(
            "DR-19", value=max_gain, ci=binding_ci,
            n=deltas[binding]["n"] if binding else None, figures=[fig],
            detail=(f"largest AUC gain from dropping any family: {max_gain} "
                    f"(family: {binding}). No noise allowance — a small positive gain inside its "
                    f"own CI is recorded as a failure (criteria.yaml DR-19 note). Full family table: "
                    f"{table_str}."),
        ))

    return results
