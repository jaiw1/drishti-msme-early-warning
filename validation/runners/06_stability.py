"""
06 Stability — PSI on the score, CSI on every input

Pre-registered criteria this runner answers: DR-13, DR-14

Consumes
--------
* `validation.runners._shared.get_oot` — reused, not refit: "the training
  window" and "the most recent window" (`criteria.yaml`'s `06_stability`
  vocabulary) are read as the SAME embargoed train/test windows runner 02
  already built for DR-05, scored by the SAME OOT model. Reusing them means
  the population-stability question this runner asks — has the score/feature
  distribution the deployed model would see actually drifted between the
  window it was fit on and the most recent one — is asked about the exact
  model and windows DR-05 already certified, rather than a second,
  independently-drawn pair that could quietly disagree with it.

Produces
--------
* `figures/psi_score.png`
* `figures/csi_features.png`
* DR-13 (PSI of the score distribution), DR-14 (max CSI across every model
  input feature, full per-feature table in the report).

Method, as pre-registered
--------------------------
10 quantile bins, edges fixed on the TRAINING window (`_shared.psi`'s
docstring), compared against the OOT test window. CSI uses the same PSI
formula per feature: `_shared.psi` for numeric columns, `_shared.
csi_categorical` (same formula, levels instead of quantile bins) for the
categorical columns already carried in `_shared.get_holdout`'s `cats` list.
"""

from __future__ import annotations

import numpy as np

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh

PSI_BINS = 10


def _psi_figure(ctx: RunnerContext, train_scores: np.ndarray, test_scores: np.ndarray, psi_value: float) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    bins = np.linspace(0, max(train_scores.max(), test_scores.max(), 1e-6), 30)
    ax.hist(train_scores, bins=bins, alpha=0.5, density=True, label="training window", color="#1f6feb")
    ax.hist(test_scores, bins=bins, alpha=0.5, density=True, label="OOT window", color="#da3633")
    ax.set_xlabel("model score")
    ax.set_ylabel("density")
    ax.set_title(f"DR-13 — score distribution PSI={psi_value:.4f}")
    ax.legend(fontsize=8)
    return sh.savefig(fig, ctx, "psi_score.png")


def _csi_figure(ctx: RunnerContext, table: list[dict], floor: float) -> str:
    import matplotlib.pyplot as plt

    table = sorted(table, key=lambda r: -r["value"])[:25]
    fig, ax = plt.subplots(figsize=(8, max(4, 0.3 * len(table))))
    colors = ["#da3633" if r["value"] > floor else "#2ea043" for r in table]
    ax.barh([r["level"] for r in table], [r["value"] for r in table], color=colors)
    ax.axvline(floor, color="#8b949e", ls="--", lw=1, label=f"DR-14 floor {floor}")
    ax.invert_yaxis()
    ax.set_xlabel("CSI")
    ax.set_title("DR-14 — CSI by feature (top 25)")
    ax.legend(fontsize=8)
    return sh.savefig(fig, ctx, "csi_features.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if not ({"DR-13", "DR-14"} & set(by_id)):
        return []

    o = sh.get_oot(ctx)
    results: list[Result] = []

    # ---- DR-13: PSI on the score -----------------------------------------
    if "DR-13" in by_id:
        value = sh.psi(o["p_train"], o["p_test"], bins=PSI_BINS)
        fig = _psi_figure(ctx, o["p_train"], o["p_test"], value)
        results.append(Result(
            "DR-13", value=round(value, 4), n=len(o["p_test"]),
            detail=(f"train window n={len(o['p_train'])} (months < {o['cut']}, embargoed), "
                    f"OOT window n={len(o['p_test'])} (months >= {o['cut']}), {PSI_BINS} quantile "
                    f"bins fixed on the training window"),
            figures=[fig],
        ))

    # ---- DR-14: max CSI across every model input feature ------------------
    if "DR-14" in by_id:
        crit = by_id["DR-14"]
        X_train, X_test = o["X_train"], o["X_test"]
        cats = set(o["cats"])
        table = []
        for col in o["cols"]:
            train_col, test_col = X_train[col], X_test[col]
            if col in cats:
                # NOT `.astype(str)`: a channel-absent column is genuinely NaN
                # (build.py's `_blank_absent_channels` / SD-D4 missingness),
                # and `.astype(str)` on a Series turns NaN into the literal
                # string "nan" — which `csi_categorical`'s `.dropna()` would
                # then no longer catch, silently promoting "missing" to a
                # spurious category level.  The raw categorical Series keeps
                # real NaNs real, so `.dropna()` still works.
                val = sh.csi_categorical(train_col, test_col)
            else:
                tr = train_col.to_numpy(dtype=float)
                te = test_col.to_numpy(dtype=float)
                tr = tr[np.isfinite(tr)]
                te = te[np.isfinite(te)]
                val = sh.psi(tr, te, bins=PSI_BINS) if len(tr) and len(te) else 0.0
            table.append(dict(level=col, value=round(float(val), 4), ci=None, n=len(o["p_test"])))
        fig = _csi_figure(ctx, table, float(crit.threshold))
        max_row = max(table, key=lambda r: r["value"]) if table else None
        results.append(Result(
            "DR-14",
            value=max_row["value"] if max_row else None,
            n=len(o["p_test"]),
            breakdown=table, figures=[fig],
            detail=f"max over {len(table)} model-input features" + (f", binding feature: {max_row['level']}" if max_row else ""),
        ))

    return results
