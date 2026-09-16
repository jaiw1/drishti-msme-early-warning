"""
01 Grouped holdout — headline discrimination, the honest Red-band number, and the book's slippage

Pre-registered criteria this runner answers: DR-01, DR-02, DR-03, DR-04

Consumes
--------
* the 45,000 x 48 panel (`validation.runners._shared.load_panel` — generated
  via `generator.build.generate`, cached under
  `data/validation_panel_cache/`), restricted to `labelable == 1`.
* `src/export_demo.py` for `CAT`, `DROP` (feature prep, imported not copied)
  and `rank_order_exhibit` (Red-band precision arithmetic, imported not
  copied).
* `src/rigor.py` for `LGB` (the LightGBM configuration `export_demo.py`
  trains with).
* `src/generator/labels.py` for `measure_base_rates` (DR-04's own arithmetic,
  already built and tested by the generator lane).

Produces
--------
* `figures/holdout_roc.png`
* `figures/red_band_precision.png`
* Results for DR-01 (grouped AUC), DR-02 (Red-band precision @ 8 months,
  report only), DR-03 (annual slippage ratio), DR-04 (label base rate, report
  only).

Method
------
Fit the production LightGBM configuration on the account-grouped training
split (`_shared.get_holdout`, `test_fraction=0.30`) and score the held-out
accounts. DR-01 is ROC-AUC pooled over every eligible holdout row (`labelable
== 1`), bootstrapped at `account_id`. DR-02 reuses `export_demo.
rank_order_exhibit`'s pooled `red_band_precision_8m` (Wilson CI, not
bootstrap — it is already a closed-form binomial CI on a single band) computed
over the SAME held-out population, pooled across every eligible month, not one
frozen snapshot month — see runner 05 for the fuller rationale, since DR-02
and DR-11/DR-12 are built from the same exhibit.

DR-03/DR-04 are properties of the GENERATED BOOK, not of this model or split,
so both are computed on the full 45k panel/accounts_static, matching the
generator's own `assert_base_rates` scope.

INTERPRETATION (DR-03, recorded here because it changes what is measured, not
because criteria.yaml's own note is ambiguous — that note is explicit and is
followed literally): DR-03's note defines `annual_slippage_ratio` as "fresh
NPA during the year / standard advances at the start of the year" — the
RBI-style ratio — explicitly DISTINCT from DR-04's `label_base_rate_annual`
(the mean of `default_within_12m`). We found that `src/generator/sources.yaml`
(`book.annual_slippage_band`) and `assert_base_rates` in
`src/generator/labels.py` in fact check the SAME [0.03, 0.05] band against
`rates.book` — i.e. against DR-04's metric, not the RBI-style ratio DR-03's
own note describes. That is an inconsistency between the generator lane's
in-script assertion and this criterion's pre-registered text. Per the brief
("if a metric name is ambiguous, implement the reading in the criterion's
note, and say so"), DR-03 here is computed exactly as criteria.yaml's note
specifies (fresh NPA over the year / standard accounts at the year's start,
averaged over the four disjoint 12-month windows the 48-month panel offers),
NOT as `rates.book`. DR-04 is reported separately via `measure_base_rates`. Both
numbers are in the report so a reviewer can see the two readings side by side.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh


def _slippage_windows(months: int, horizon: int = sh.HORIZON) -> list[tuple[int, int]]:
    """Disjoint `horizon`-month windows fully inside the panel's [0, months-1] range."""
    return [(s, s + horizon - 1) for s in range(0, months, horizon) if s + horizon - 1 <= months - 1]


def _slippage_ratio(accounts: pd.DataFrame, months: int) -> float | None:
    """DR-03: mean, over the panel's disjoint 12-month windows, of
    (fresh NPA during the window) / (standard advances at the window's start).
    """
    npa = accounts["npa_month"].to_numpy(dtype=float)
    npa = np.where(npa < 0, np.nan, npa)
    ratios = []
    for s, e in _slippage_windows(months):
        standard = np.isnan(npa) | (npa >= s)
        fresh = (~np.isnan(npa)) & (npa >= s) & (npa <= e)
        denom = int(standard.sum())
        if denom > 0:
            ratios.append(fresh.sum() / denom)
    return float(np.mean(ratios)) if ratios else None


def _roc_figure(ctx: RunnerContext, y: np.ndarray, p: np.ndarray, auc: float) -> str:
    from sklearn.metrics import roc_curve
    import matplotlib.pyplot as plt

    fpr, tpr, _ = roc_curve(y, p)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(fpr, tpr, color="#1f6feb", lw=2, label=f"holdout ROC (AUC={auc:.3f})")
    ax.plot([0, 1], [0, 1], color="#8b949e", lw=1, ls="--", label="chance")
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("DR-01 — grouped holdout ROC")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    return sh.savefig(fig, ctx, "holdout_roc.png")


def _red_band_figure(ctx: RunnerContext, exhibit: dict) -> str:
    import matplotlib.pyplot as plt

    bands = exhibit["by_band"]
    names = [b["band"] for b in bands]
    rates = [b["bad_rate"] for b in bands]
    lo = [b["bad_rate"] - b["ci_lo"] for b in bands]
    hi = [b["ci_hi"] - b["bad_rate"] for b in bands]
    colors = {"Green": "#2ea043", "Amber": "#d29922", "Red": "#da3633"}

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar(names, rates, yerr=[lo, hi], capsize=4,
           color=[colors.get(n, "#8b949e") for n in names])
    ax.set_ylabel("realised default rate within 8 months")
    ax.set_title("DR-02 — Red-band precision @ 8 months (95% Wilson CI)")
    for i, b in enumerate(bands):
        ax.text(i, b["bad_rate"] + 0.01, f"{b['bad_rate']:.1%}\n(n={b['n']})",
                ha="center", fontsize=8)
    return sh.savefig(fig, ctx, "red_band_precision.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    results: list[Result] = []
    seed = sh.get_seed(ctx)

    h = sh.get_holdout(ctx)
    y_test, p_test, df_test = h["y_test"], h["p_test"], h["df_test"]

    # ---- DR-01: grouped AUC --------------------------------------------
    if "DR-01" in by_id:
        auc = sh.grouped_auc(y_test, p_test)
        boot_df = pd.DataFrame({
            "account_id": df_test["account_id"].to_numpy(),
            "y": y_test, "p": p_test,
        })
        ci = sh.bootstrap_ci(
            boot_df, lambda d: sh.grouped_auc(d["y"].to_numpy(), d["p"].to_numpy()),
            n=sh.n_boot(ctx), seed=seed,
        )
        fig = _roc_figure(ctx, y_test, p_test, auc)
        results.append(Result(
            "DR-01", value=round(auc, 4) if auc is not None else None, ci=ci,
            n=len(y_test),
            detail=f"pooled ROC-AUC over every eligible holdout row (n_accounts={df_test['account_id'].nunique()})",
            figures=[fig],
        ))

    # ---- DR-02 / rank-order exhibit (shared with runner 05) -------------
    exhibit = sh.get_rank_order_exhibit(ctx)
    if "DR-02" in by_id:
        rbp = exhibit["red_band_precision_8m"]
        thr = exhibit.get("_thresholds", {})
        fig = _red_band_figure(ctx, exhibit)
        results.append(Result(
            "DR-02", value=rbp["precision"], ci=(rbp["ci_lo"], rbp["ci_hi"]), n=rbp["n"],
            detail=(f"Red-band precision at 8 months before NPA onset, pooled over every "
                    f"eligible holdout row (not a single snapshot month); {rbp['hits']}/{rbp['n']} "
                    f"hits, 95% Wilson CI. Reported alongside base rate (DR-04) and raw accuracy "
                    f"is not computed — that is the number this criterion exists to replace. "
                    f"Operating thresholds: amber={thr.get('amber')}, red={thr.get('red')} "
                    f"({'live cost-minimising, from data/demo_data.json' if thr.get('is_live') else 'FALLBACK — legacy 0.04/0.40, live thresholds file unavailable'})."),
            figures=[fig],
        ))

    # ---- DR-03 / DR-04: book-level rates, on the FULL generated book ----
    panel, accounts = h["panel"], h["accounts"]
    n, months = sh._panel_size(ctx)
    if "DR-03" in by_id:
        value = _slippage_ratio(accounts, months)
        acc_df = accounts[["account_id", "npa_month"]].copy()
        ci = sh.bootstrap_ci(
            acc_df, lambda d: _slippage_ratio(d, months),
            group_col="account_id", n=sh.n_boot(ctx), seed=seed,
        )
        windows = _slippage_windows(months)
        results.append(Result(
            "DR-03", value=round(value, 4) if value is not None else None, ci=ci,
            n=len(accounts),
            detail=(f"RBI-style ratio (fresh NPA / standard advances at window start), mean over "
                    f"{len(windows)} disjoint 12-month windows {windows}. See this runner's module "
                    f"docstring for why this reading differs from what "
                    f"src/generator/labels.py's assert_base_rates actually checks."),
        ))

    if "DR-04" in by_id:
        sh._ensure_src_on_path(ctx.repo_root)
        from generator.labels import measure_base_rates
        rates = measure_base_rates(panel, accounts)
        labelable = panel[panel["labelable"] == 1]
        acc_df = pd.DataFrame({
            "account_id": labelable["account_id"].astype(str).to_numpy(),
            "y": labelable["default_within_12m"].to_numpy(),
        })
        ci = sh.bootstrap_ci(
            acc_df, lambda d: float(d["y"].mean()) if len(d) else None,
            n=sh.n_boot(ctx), seed=seed,
        )
        results.append(Result(
            "DR-04", value=round(rates.book, 4), ci=ci, n=len(labelable),
            detail=(f"mean(default_within_12m) over labelable rows, via "
                    f"generator.labels.measure_base_rates (the same call the generator's own "
                    f"in-script assertion uses). SMA-2/12m-NPA event ratio = {rates.sma2_to_npa_events:.2f}."),
        ))

    return results
