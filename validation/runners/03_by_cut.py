"""
03 Per-portfolio floor and the full by-cut table

Pre-registered criteria this runner answers: DR-06, DR-07

Consumes
--------
* `validation.runners._shared.get_holdout` — the SAME grouped-holdout model
  and predictions DR-01 reports (never a second split; a per-cut AUC has to
  be sliced from the one number DR-01 already certified, or the two tables
  could quietly disagree).
* `validation.criteria.CriteriaDoc.cuts` — the nine registered cuts, resolved
  via `_shared.cut_series` (cut id first, source_column second; ticket/vintage
  bands built from the pre-registered binning rules).

Produces
--------
* `figures/auc_by_portfolio.png`
* `figures/auc_by_cut_grid.png`
* DR-06: one breakdown cell per portfolio (8 cells, `min_n=0` — the floor
  applies regardless of cell size, per the `portfolio` cut's own ruling).
* DR-07: one breakdown cell per LEVEL of EVERY one of the nine cuts
  (`cut: all`), labelled `"<cut_id>=<level>"`, `min_n=500`.

Method, as pre-registered
--------------------------
AUC with a group-level bootstrap CI and an n, for every level of all nine
registered cuts, computed on the grouped-holdout test set (the same
population and scores DR-01 reports on). Cells below `min_n` are still
computed and reported — the harness marks them `skipped_low_n`, never drops
them (per `criteria.yaml decision_rule.low_n`).

Runtime note: DR-07 alone is ~40-60 cells (9 cuts x their levels). Each cell's
bootstrap CI uses `_shared.n_boot(ctx)` resamples (200 by default — see
`_shared.py`'s module docstring for why 1000 was impractical at this row
count); a typical DR-07 cell is a small fraction of the ~470k-row holdout
test, so even 200 resamples per cell keeps the whole table in well under a
minute.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh


def _cell(df: pd.DataFrame, y: np.ndarray, p: np.ndarray, mask: np.ndarray, ctx: RunnerContext,
          seed: int, label: str) -> dict:
    n = int(mask.sum())
    if n == 0:
        return dict(level=label, value=None, ci=None, n=0)
    y_sub, p_sub = y[mask], p[mask]
    auc = sh.grouped_auc(y_sub, p_sub)
    boot_df = pd.DataFrame({
        "account_id": df["account_id"].to_numpy()[mask], "y": y_sub, "p": p_sub,
    })
    ci = sh.bootstrap_ci(
        boot_df, lambda d: sh.grouped_auc(d["y"].to_numpy(), d["p"].to_numpy()),
        n=sh.n_boot(ctx), seed=seed,
    )
    return dict(level=label, value=round(auc, 4) if auc is not None else None, ci=ci, n=n)


def _portfolio_figure(ctx: RunnerContext, cells: list[dict], floor: float) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4))
    labels = [c["level"] for c in cells]
    values = [c["value"] if c["value"] is not None else 0 for c in cells]
    lo = [v - (c["ci"][0] if c["ci"] else v) for v, c in zip(values, cells)]
    hi = [(c["ci"][1] if c["ci"] else v) - v for v, c in zip(values, cells)]
    colors = ["#2ea043" if v >= floor else "#da3633" for v in values]
    ax.bar(labels, values, yerr=[lo, hi], capsize=3, color=colors)
    ax.axhline(floor, color="#8b949e", ls="--", lw=1, label=f"DR-06 floor {floor}")
    ax.set_ylabel("AUC")
    ax.set_title("DR-06 — AUC by portfolio (95% CI)")
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=8)
    return sh.savefig(fig, ctx, "auc_by_portfolio.png")


def _cut_grid_figure(ctx: RunnerContext, by_cut: dict[str, list[dict]]) -> str:
    import matplotlib.pyplot as plt

    cuts = list(by_cut)
    ncols = 3
    nrows = -(-len(cuts) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows), squeeze=False)
    for i, cut_id in enumerate(cuts):
        ax = axes[i // ncols][i % ncols]
        cells = [c for c in by_cut[cut_id] if c["value"] is not None]
        if cells:
            ax.bar([c["level"] for c in cells], [c["value"] for c in cells], color="#1f6feb")
        ax.set_title(cut_id, fontsize=9)
        ax.set_ylim(0, 1)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=6)
    for j in range(len(cuts), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.suptitle("DR-07 — AUC by cut level", y=1.02)
    return sh.savefig(fig, ctx, "auc_by_cut_grid.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    results: list[Result] = []
    seed = sh.get_seed(ctx)

    h = sh.get_holdout(ctx)
    df, y, p = h["df_test"], h["y_test"], h["p_test"]

    # ---- DR-06: per-portfolio floor --------------------------------------
    if "DR-06" in by_id:
        crit = by_id["DR-06"]
        portfolio_cut = next((c for c in ctx.doc.cuts if c.id == "portfolio"), None)
        levels = portfolio_cut.levels if portfolio_cut and portfolio_cut.levels else sorted(df["portfolio"].astype(str).unique())
        cells = []
        for lvl in levels:
            mask = (df["portfolio"].astype(str) == lvl).to_numpy()
            cells.append(_cell(df, y, p, mask, ctx, seed, lvl))
        fig = _portfolio_figure(ctx, cells, float(crit.threshold))
        results.append(Result("DR-06", breakdown=cells, figures=[fig],
                               detail="AUC per portfolio, grouped-holdout test set, 95% group-bootstrap CI"))

    # ---- DR-07: the full by-cut table ------------------------------------
    if "DR-07" in by_id:
        by_cut: dict[str, list[dict]] = {}
        flat_cells: list[dict] = []
        for cut in ctx.doc.cuts:
            series = sh.cut_series(cut, df)
            levels = cut.levels if cut.levels else sh.sorted_levels(series.dropna().unique().tolist())
            cells = []
            for lvl in levels:
                mask = (series == lvl).to_numpy()
                cell = _cell(df, y, p, mask, ctx, seed, lvl)
                cells.append(cell)
                flat_cells.append(dict(cell, level=f"{cut.id}={lvl}"))
            by_cut[cut.id] = cells
        fig = _cut_grid_figure(ctx, by_cut)
        results.append(Result("DR-07", breakdown=flat_cells, figures=[fig],
                               detail=f"{len(flat_cells)} cells across {len(by_cut)} cuts"))

    return results
