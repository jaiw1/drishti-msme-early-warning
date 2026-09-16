"""
02 Out-of-time — does the model survive later calendar months

Pre-registered criteria this runner answers: DR-05

Consumes
--------
* the 45,000 x 48 panel (`validation.runners._shared`), restricted to
  `labelable == 1`.
* `validation.runners._shared.get_holdout` for the grouped holdout AUC (the
  denominator).
* `validation.runners._shared.get_oot` for the embargoed out-of-time
  train/test split and the model fit on it.

Produces
--------
* `figures/oot_auc_by_month.png`
* one Result for DR-05: `oot_auc_ratio_to_holdout = AUC(OOT test) / AUC(grouped
  holdout)`.

Method, as pre-registered
--------------------------
`criteria.yaml splits.oot` requires the out-of-time test window to carry "at
least 12 months of realised label horizon" and requires training rows whose
12-month forward window would reach past the cut to be embargoed.
`_shared.oot_cut_month` derives the cut month from that requirement directly
(`months - 2*horizon`, the tightest cut that still leaves >= horizon labelable
test months) rather than reusing `src/rigor.py`'s fixed `CUT = 18`, which was
calibrated for the 36-month panel `rigor.py` was written against and does not
itself satisfy the ">= 12 realised months" requirement at 36 or 48 months (see
`_shared.oot_cut_month`'s docstring for the arithmetic). A fresh LightGBM model
(the same `rigor.LGB` configuration) is trained on the embargoed early months
and scored on the late ones; DR-05 is that AUC divided by DR-01's grouped
holdout AUC.

The CI is a bootstrap over the RATIO, not over either AUC alone: the holdout
test set and the OOT test set are resampled independently (they share no rows
— different accounts is not guaranteed, since OOT slices by time not by
account, but the two AUCs are still computed from disjoint row sets so
treating them as independent for the bootstrap is conservative, not
optimistic) at 1000 joint draws, `ratio = auc(holdout_resample) /
auc(oot_resample)`... inverted to `auc(oot)/auc(holdout)` per DR-05's stated
direction.

Status
------
Implemented.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh


def _oot_figure(ctx: RunnerContext, df_train: pd.DataFrame, y_train, p_train,
                df_test: pd.DataFrame, y_test, p_test, cut: int) -> str:
    import matplotlib.pyplot as plt
    from sklearn.metrics import roc_auc_score

    def _by_month(df, y, p):
        d = pd.DataFrame({"month_idx": df["month_idx"].to_numpy(), "y": y, "p": p})
        rows = []
        for m, g in d.groupby("month_idx"):
            if g["y"].nunique() < 2:
                continue
            rows.append((m, roc_auc_score(g["y"], g["p"]), len(g)))
        return rows

    train_pts = _by_month(df_train, y_train, p_train)
    test_pts = _by_month(df_test, y_test, p_test)

    fig, ax = plt.subplots(figsize=(7, 4))
    if train_pts:
        ax.plot([m for m, _, _ in train_pts], [a for _, a, _ in train_pts],
                "o-", color="#1f6feb", label="train window (embargoed)")
    if test_pts:
        ax.plot([m for m, _, _ in test_pts], [a for _, a, _ in test_pts],
                "o-", color="#da3633", label="OOT test window")
    ax.axvline(cut, color="#8b949e", ls="--", lw=1, label=f"cut = month {cut}")
    ax.set_xlabel("observation month_idx")
    ax.set_ylabel("AUC (that month's rows)")
    ax.set_title("DR-05 — AUC by calendar month, train vs out-of-time")
    ax.legend(fontsize=8)
    return sh.savefig(fig, ctx, "oot_auc_by_month.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if "DR-05" not in by_id:
        return []
    seed = sh.get_seed(ctx)

    h = sh.get_holdout(ctx)
    o = sh.get_oot(ctx)

    holdout_auc = sh.grouped_auc(h["y_test"], h["p_test"])
    oot_auc = sh.grouped_auc(o["y_test"], o["p_test"])
    ratio = (oot_auc / holdout_auc) if (holdout_auc and oot_auc is not None) else None

    hold_df = pd.DataFrame({
        "account_id": h["df_test"]["account_id"].to_numpy(), "y": h["y_test"], "p": h["p_test"],
    })
    oot_df = pd.DataFrame({
        "account_id": o["df_test"]["account_id"].to_numpy(), "y": o["y_test"], "p": o["p_test"],
    })

    n = sh.n_boot(ctx)
    rng_seed = seed
    # Two independent group-level bootstraps, paired by draw index, so the
    # ratio's spread reflects both AUCs' sampling variation rather than just
    # one of them.
    hold_stats = _bootstrap_auc_draws(hold_df, n=n, seed=rng_seed)
    oot_stats = _bootstrap_auc_draws(oot_df, n=n, seed=rng_seed + 1)
    m = min(len(hold_stats), len(oot_stats))
    ratios = [oot_stats[i] / hold_stats[i] for i in range(m) if hold_stats[i]]
    if ratios:
        lo = float(np.percentile(ratios, 2.5))
        hi = float(np.percentile(ratios, 97.5))
        ci = (round(lo, 4), round(hi, 4))
    else:
        ci = (0.0, 0.0)

    fig = _oot_figure(
        ctx, o["df_train"], o["y_train"], o["p_train"],
        o["df_test"], o["y_test"], o["p_test"], o["cut"],
    )

    return [Result(
        "DR-05",
        value=round(ratio, 4) if ratio is not None else None,
        ci=ci, n=len(o["y_test"]),
        detail=(f"OOT AUC {oot_auc:.4f} (n={len(o['y_test'])}, cut=month {o['cut']}, "
                f"train n={len(o['y_train'])}) / grouped holdout AUC {holdout_auc:.4f} "
                f"(n={len(h['y_test'])})"),
        figures=[fig],
    )]


def _bootstrap_auc_draws(df: pd.DataFrame, n: int, seed: int) -> list[float]:
    d = df.reset_index(drop=True)
    rng = np.random.default_rng(seed)
    idx_by_group = d.groupby("account_id", observed=True, sort=False).indices
    idx_lists = list(idx_by_group.values())
    ngroups = len(idx_lists)
    if ngroups == 0:
        return []
    out = []
    for _ in range(n):
        chosen = rng.integers(0, ngroups, size=ngroups)
        rows = np.concatenate([idx_lists[i] for i in chosen])
        sub = d.iloc[rows]
        auc = sh.grouped_auc(sub["y"].to_numpy(), sub["p"].to_numpy())
        if auc is not None:
            out.append(auc)
    return out
