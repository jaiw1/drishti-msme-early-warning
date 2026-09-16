"""
12 Baseline ladder — how much of the gain is the model

Pre-registered criteria this runner answers: DR-26

Consumes
--------
* `validation.runners._shared.get_holdout` — the SAME grouped-holdout split
  DR-01 reports on (45,000 x 48, seed 7). Rung 1 (DPD-only) and rung 2
  (logistic scorecard) are fit HERE, on that exact split, so all three rungs
  share one apples-to-apples population and CI methodology; rung 3 reuses
  DR-01's own fitted LightGBM (`h["p_test"]`) at zero extra cost.
* `data/rigor.json` `baseline_ladder[]` — `src/rigor.py`'s own logistic-
  scorecard and LightGBM numbers (same seed/split/config), read for a
  same/different cross-check against the two rungs computed here.

Produces
--------
* `figures/baseline_ladder.png`
* DR-26: AUC for three rungs, each with a group-bootstrap CI, on the SAME
  holdout.

Method, as pre-registered
--------------------------
Rung 1, "DPD-only rule": a logistic regression fit on ONLY the DPD family's
columns (`src/rigor.py GROUPS["Days-past-due / repayment"]`) — the simplest
model that uses just "is this account already visibly late", the rule DRISHTi's
whole early-lead thesis exists to beat. Rung 2, "logistic-regression
scorecard": a logistic regression over every model input (numeric columns +
one-hot categoricals), mirroring `src/rigor.py`'s own baseline-ladder fit
exactly (same split, same feature set). Rung 3, "LightGBM (ours)": DR-01's
own fitted model, reused rather than refit.
"""

from __future__ import annotations

import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh

INPUTS: tuple[str, ...] = ("data/msme_loan_panel.csv", "data/rigor.json")


def _fit_logistic(X_tr, y_tr, X_te, cats: list[str]):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    num = [c for c in X_tr.columns if c not in cats]
    Xtr_l = pd.concat([X_tr[num], pd.get_dummies(X_tr[cats])], axis=1) if cats else X_tr[num]
    Xte_l = pd.concat([X_te[num], pd.get_dummies(X_te[cats])], axis=1) if cats else X_te[num]
    Xte_l = Xte_l.reindex(columns=Xtr_l.columns, fill_value=0)
    pipe = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                          LogisticRegression(max_iter=1000, class_weight="balanced"))
    pipe.fit(Xtr_l, y_tr)
    return pipe.predict_proba(Xte_l)[:, 1]


def _figure(ctx: RunnerContext, rungs: list[dict]) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.5, 4))
    labels = [r["model"] for r in rungs]
    values = [r["auc"] for r in rungs]
    lo = [v - (r["ci"][0] if r["ci"] else v) for v, r in zip(values, rungs)]
    hi = [(r["ci"][1] if r["ci"] else v) - v for v, r in zip(values, rungs)]
    ax.bar(labels, values, yerr=[lo, hi], capsize=4, color=["#8b949e", "#d29922", "#1f6feb"])
    ax.set_ylim(0.4, 1.0)
    ax.set_ylabel("AUC (grouped holdout)")
    ax.set_title("DR-26 — baseline ladder")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right", fontsize=8)
    return sh.savefig(fig, ctx, "baseline_ladder.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if "DR-26" not in by_id:
        return []

    seed = sh.get_seed(ctx)
    h = sh.get_holdout(ctx)  # calls sh.load_panel -> _ensure_src_on_path first
    import rigor
    import json

    X, y, tr, te, cats, df_test = h["X"], h["y"], h["train_idx"], h["test_idx"], h["cats"], h["df_test"]
    y_test = h["y_test"]

    dpd_cols = [c for c in rigor.GROUPS["Days-past-due / repayment"] if c in X.columns]
    p_dpd = _fit_logistic(X[dpd_cols].iloc[tr], y[tr], X[dpd_cols].iloc[te], cats=[])
    auc_dpd = sh.grouped_auc(y_test, p_dpd)

    p_scorecard = _fit_logistic(X.iloc[tr], y[tr], X.iloc[te], cats=cats)
    auc_scorecard = sh.grouped_auc(y_test, p_scorecard)

    auc_lgbm = sh.grouped_auc(y_test, h["p_test"])

    def _ci(p):
        boot_df = pd.DataFrame({"account_id": df_test["account_id"].to_numpy(), "y": y_test, "p": p})
        return sh.bootstrap_ci(boot_df, lambda d: sh.grouped_auc(d["y"].to_numpy(), d["p"].to_numpy()),
                                n=sh.n_boot(ctx), seed=seed)

    rungs = [
        dict(model="DPD-only rule (logistic, {} cols)".format(len(dpd_cols)),
             auc=round(auc_dpd, 4) if auc_dpd is not None else None, ci=_ci(p_dpd), n=len(te)),
        dict(model="Logistic regression (scorecard-style)",
             auc=round(auc_scorecard, 4) if auc_scorecard is not None else None, ci=_ci(p_scorecard), n=len(te)),
        dict(model="LightGBM (ours)",
             auc=round(auc_lgbm, 4) if auc_lgbm is not None else None, ci=_ci(h["p_test"]), n=len(te)),
    ]
    fig = _figure(ctx, rungs)

    rigor_path = ctx.repo_root / "data" / "rigor.json"
    cross_check = "data/rigor.json not available for cross-check"
    if rigor_path.is_file():
        try:
            rj = json.loads(rigor_path.read_text())
            cross_check = f"data/rigor.json baseline_ladder: {rj.get('baseline_ladder')}"
        except Exception as exc:
            cross_check = f"data/rigor.json unreadable: {exc}"

    deltas = (f"scorecard -> LightGBM: {round((auc_lgbm or 0) - (auc_scorecard or 0), 4)}; "
              f"DPD-only -> scorecard: {round((auc_scorecard or 0) - (auc_dpd or 0), 4)}")

    return [Result(
        "DR-26", value=rungs[-1]["auc"], ci=rungs[-1]["ci"], n=len(te), figures=[fig],
        breakdown=[dict(level=r["model"], value=r["auc"], ci=r["ci"], n=r["n"]) for r in rungs],
        detail=(f"three rungs on the SAME 45,000 x 48 grouped-holdout split (seed {seed}): "
                f"{[(r['model'], r['auc'], r['ci']) for r in rungs]}. Deltas: {deltas}. {cross_check}. "
                f"REPORTED, no pre-registered band (criteria.yaml DR-26 note)."),
    )]
