"""
04 Calibration — does a PD of 40% mean 40%

Pre-registered criteria this runner answers: DR-08, DR-09, DR-10

Consumes
--------
* `validation.runners._shared.get_calibration` — an inner grouped split of the
  HOLDOUT TRAIN set (75/25, `test_size=0.25`, mirroring `src/rigor.py`'s own
  calibration section): a model is fit on the inner-train 75%, isotonic
  regression is fit on that model's predictions on the inner-val 25%, and both
  the raw and calibrated scores are then produced on the HOLDOUT TEST set
  (`_shared.get_holdout`'s `test_idx`) — i.e. the isotonic map is fit on a fold
  the test set never touches, per the brief's "isotonic on a held-out fold".
* `validation.criteria.CriteriaDoc.cuts` for DR-09's per-cut breakdown, via
  `_shared.cut_series` (same resolution as runner 03).

Produces
--------
* `figures/reliability_overall.png`
* `figures/ece_by_cut.png`
* DR-08 (ECE overall, calibrated score), DR-09 (ECE per cut, calibrated
  score, `min_n=500`), DR-10 (Brier(calibrated) - Brier(raw), same test set).

INTERPRETATION: `criteria.yaml` does not say whether DR-08/DR-09's ECE is
measured on the RAW model score or the isotonic-CALIBRATED one, and
`export_demo.py`'s shipped pipeline does not itself calibrate — the `pd` field
the cockpit reads is the raw LightGBM probability. Two readings are
defensible; we picked the CALIBRATED one, for two reasons: (1) `rigor.py`'s
own reliability table — the only precedent in this codebase — reports
`pred=pred_cal`, i.e. it already treats "the calibrated score" as the number a
reliability curve is drawn against; (2) DR-10 exists specifically to check
whether isotonic calibration is even worth having, which only makes sense to
read alongside an ECE gate that assumes the calibration step is in the
pipeline. `_shared.ece`'s bin count (10, equal-width) is also not pinned by
criteria.yaml; 10 was chosen as the standard ECE convention and to match this
codebase's existing 10-bin reliability-curve convention. Both choices are
recorded here, at registration-adjacent time, per the brief's instruction to
record an interpretation call rather than resolve it silently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh

ECE_BINS = 10


def _reliability_figure(ctx: RunnerContext, y: np.ndarray, p_cal: np.ndarray, ece_value: float) -> str:
    import matplotlib.pyplot as plt

    edges = np.linspace(0, 1, ECE_BINS + 1)
    idx = np.clip(np.digitize(p_cal, edges[1:-1], right=True), 0, ECE_BINS - 1)
    xs, ys, ns = [], [], []
    for b in range(ECE_BINS):
        mask = idx == b
        if not mask.any():
            continue
        xs.append(p_cal[mask].mean())
        ys.append(y[mask].mean())
        ns.append(int(mask.sum()))

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], color="#8b949e", ls="--", lw=1, label="perfect calibration")
    sizes = np.array(ns, dtype=float)
    sizes = 20 + 200 * sizes / max(sizes.max(), 1)
    ax.scatter(xs, ys, s=sizes, color="#1f6feb", alpha=0.8, label="calibrated bins")
    ax.set_xlabel("mean predicted PD (calibrated)")
    ax.set_ylabel("observed default rate")
    ax.set_title(f"DR-08 — reliability (ECE={ece_value:.4f})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)
    return sh.savefig(fig, ctx, "reliability_overall.png")


def _ece_by_cut_figure(ctx: RunnerContext, cells_by_cut: dict[str, list[dict]], floor: float) -> str:
    import matplotlib.pyplot as plt

    cuts = list(cells_by_cut)
    ncols = 3
    nrows = -(-len(cuts) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows), squeeze=False)
    for i, cut_id in enumerate(cuts):
        ax = axes[i // ncols][i % ncols]
        cells = [c for c in cells_by_cut[cut_id] if c["value"] is not None]
        if cells:
            colors = ["#da3633" if c["value"] > floor else "#2ea043" for c in cells]
            ax.bar([c["level"] for c in cells], [c["value"] for c in cells], color=colors)
            ax.axhline(floor, color="#8b949e", ls="--", lw=1)
        ax.set_title(cut_id, fontsize=9)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=6)
    for j in range(len(cuts), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.suptitle("DR-09 — ECE by cut level", y=1.02)
    return sh.savefig(fig, ctx, "ece_by_cut.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    results: list[Result] = []
    seed = sh.get_seed(ctx)

    cal = sh.get_calibration(ctx)
    y = cal["y_test"]
    p_raw, p_cal = cal["p_raw_test"], cal["p_cal_test"]
    df_test = cal["df_test"]

    # ---- DR-08: overall ECE (calibrated) ---------------------------------
    if "DR-08" in by_id:
        value = sh.ece(y, p_cal, n_bins=ECE_BINS)
        boot_df = pd.DataFrame({
            "account_id": df_test["account_id"].to_numpy(), "y": y, "p": p_cal,
        })
        ci = sh.bootstrap_ci(
            boot_df, lambda d: sh.ece(d["y"].to_numpy(), d["p"].to_numpy(), n_bins=ECE_BINS),
            n=sh.n_boot(ctx, ece=True), seed=seed,
        )
        fig = _reliability_figure(ctx, y, p_cal, value)
        results.append(Result(
            "DR-08", value=round(value, 4), ci=ci, n=len(y),
            detail=f"{ECE_BINS} equal-width bins, calibrated score, held-out fold isotonic",
            figures=[fig],
        ))

    # ---- DR-09: per-cut ECE (calibrated) ----------------------------------
    if "DR-09" in by_id:
        crit = by_id["DR-09"]
        cells_by_cut: dict[str, list[dict]] = {}
        flat: list[dict] = []
        for cut in ctx.doc.cuts:
            series = sh.cut_series(cut, df_test)
            levels = cut.levels if cut.levels else sh.sorted_levels(series.dropna().unique().tolist())
            cells = []
            for lvl in levels:
                mask = (series == lvl).to_numpy()
                n = int(mask.sum())
                if n == 0:
                    cells.append(dict(level=lvl, value=None, ci=None, n=0))
                    continue
                y_sub, p_sub = y[mask], p_cal[mask]
                val = sh.ece(y_sub, p_sub, n_bins=ECE_BINS)
                boot_df = pd.DataFrame({
                    "account_id": df_test["account_id"].to_numpy()[mask], "y": y_sub, "p": p_sub,
                })
                ci = sh.bootstrap_ci(
                    boot_df, lambda d: sh.ece(d["y"].to_numpy(), d["p"].to_numpy(), n_bins=ECE_BINS),
                    n=sh.n_boot(ctx, ece=True), seed=seed,
                )
                cells.append(dict(level=lvl, value=round(val, 4), ci=ci, n=n))
                flat.append(dict(level=f"{cut.id}={lvl}", value=round(val, 4), ci=ci, n=n))
            cells_by_cut[cut.id] = cells
        fig = _ece_by_cut_figure(ctx, cells_by_cut, float(crit.threshold))
        results.append(Result("DR-09", breakdown=flat, figures=[fig],
                               detail=f"{len(flat)} cells across {len(cells_by_cut)} cuts, calibrated score"))

    # ---- DR-10: Brier(calibrated) - Brier(raw) -----------------------------
    if "DR-10" in by_id:
        b_raw = sh.brier(y, p_raw)
        b_cal = sh.brier(y, p_cal)
        delta = b_cal - b_raw
        boot_df = pd.DataFrame({
            "account_id": df_test["account_id"].to_numpy(), "y": y, "p_raw": p_raw, "p_cal": p_cal,
        })
        ci = sh.bootstrap_ci(
            boot_df,
            lambda d: sh.brier(d["y"].to_numpy(), d["p_cal"].to_numpy()) - sh.brier(d["y"].to_numpy(), d["p_raw"].to_numpy()),
            n=sh.n_boot(ctx, ece=True), seed=seed,
        )
        results.append(Result(
            "DR-10", value=round(delta, 6), ci=ci, n=len(y),
            detail=f"Brier(raw)={b_raw:.4f}, Brier(calibrated)={b_cal:.4f}",
        ))

    return results
