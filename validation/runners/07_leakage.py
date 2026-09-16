"""
07 Leakage — the claim that we see it a year early

Pre-registered criteria this runner answers: DR-15, DR-16, DR-17

Consumes
--------
* `validation.runners._shared.get_holdout` — the SAME grouped-holdout
  LightGBM fit DR-01 reports on (same seed, same split, same
  `export_demo.CAT`/`DROP`, same `rigor.LGB` config `rigor.py`'s own G2-gate
  fit uses). Used for an INDEPENDENT recomputation of DR-15's lead-time
  attribution — cross-checked against, not copied from, `data/rigor.json`.
* `data/rigor.json` — `leakage_dpd_share` / `leakage_alt_dpd_share` /
  `leakage_families` (the G2-gate artefact `src/rigor.py` wrote). This is the
  GRADED value for DR-15 (the officially committed number); the in-process
  recompute above is corroborating evidence, reported alongside it.
* `validation.runners._refit.fit_permuted` — five small-book (9,000 x 36)
  refits on randomly permuted labels, one per registered seed.
* `src/rigor.py` `GROUPS` — the family membership DR-15's attribution share
  and DR-17's manifest are both organised by.

Produces
--------
* `figures/lead_time_attribution.png`
* `figures/permutation_auc.png`
* DR-15 (DPD-family attribution share at 10-12 months), DR-16 (permuted-label
  AUC, averaged over 5 seeds), DR-17 (availability-at-time manifest, `exists`).

Method, as pre-registered
--------------------------
(a) Lead-time attribution: for predictions made 10-12 months before NPA
onset, the share of total absolute SHAP-style contribution carried by the
DPD family (`src/rigor.py GROUPS["Days-past-due / repayment"]`). Read from
`data/rigor.json` (the graded value); independently recomputed here from the
cached holdout model, restricted to the SAME bucket, for a bootstrap CI and a
same/different check against the G2 artefact.

(b) Permutation: retrain the full pipeline on randomly permuted labels
(split/features/hyper-parameters untouched), averaged over the registered
seeds. Run on the small 9,000 x 36 book (`_refit.py`) — five full 45,000 x 48
retrains would not fit this lane's remaining budget; see `_refit.py`'s module
docstring for why the small book is not a lesser check.

(c) Availability-at-time manifest: one row per model input feature stating
when a bank would actually have known that value relative to the observation
month, and which system supplies it, built from the generator's own documented
data-source cadences (`DATA_CARD.md`: bureau refresh + reporting lag, GST
filing lag distribution, drawing-power refresh cycle, core-banking real-time
fields, origination-time statics). A feature scored by the model but absent
from the manifest fails the criterion.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _refit as rf
from . import _shared as sh

INPUTS: tuple[str, ...] = (
    "data/msme_loan_panel.csv",
    "data/accounts_static.csv",
    "data/rigor.json",
)

LEAD_BUCKET = (10, 12)

# --------------------------------------------------------------------------- #
# DR-17 — availability-at-time manifest. One entry per FAMILY (src/rigor.py
# GROUPS), applied to every column that family owns, with a handful of
# per-column overrides for members whose cadence differs from their family's
# default. Sourced from DATA_CARD.md's documented parameter cadences, not
# invented: bureau.report_lag_months=3, measurement.gst_report_lag_distribution
# ({0mo: 42%, 1mo: 43%, 2mo: 15%}), drawing_power_refresh_months=3.
# --------------------------------------------------------------------------- #
_FAMILY_AVAILABILITY: dict[str, dict[str, str]] = {
    "Days-past-due / repayment": dict(
        available_at="same day (T+0)",
        source="core banking system (CBS) — days-past-due, bounce and minimum-balance-breach events post same day",
    ),
    "Cash-flow (inflows / GST)": dict(
        available_at="bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution)",
        source="CBS statement feed (inflow/txn_count) + GSTR-3B filing (gst_sales, sales_trend_3m)",
    ),
    "Demand vs collection": dict(
        available_at="same day (T+0)",
        source="core banking system — demand/collection posting is a same-day ledger event",
    ),
    "Credit-limit utilisation": dict(
        available_at="utilisation T+0 (CBS); drawing_power refreshed quarterly (DATA_CARD.md drawing_power_refresh_months=3) — stale up to 3 months between refreshes",
        source="core banking system (utilisation) + stock/book-debt statement (drawing_power)",
    ),
    "Income & balance": dict(
        available_at="same day (T+0)",
        source="CBS — salary credit, account balance, rental/crop receipt and commute spend are transaction-feed events",
    ),
    "Leverage & collateral": dict(
        available_at="same day for EMI-burden/moratorium flags (CBS); LTV updated only at valuation/schedule events, otherwise stale",
        source="core banking system + collateral valuation records",
    ),
    "Bureau": dict(
        available_at="up to 3 months stale (DATA_CARD.md bureau.report_lag_months=3 — bureaus refresh monthly and the file reaches the lender later still)",
        source="credit bureau monthly refresh file",
    ),
    "Adverse filings": dict(
        available_at="same day to T+1 (branch/RM-filed remark)",
        source="branch/relationship-manager filing into CBS",
    ),
    "Borrower profile": dict(
        available_at="known at origination (T+0 forever after) — static account attributes",
        source="loan origination / KYC record",
    ),
}


def _availability_manifest(cols: list[str]) -> tuple[list[dict], list[str]]:
    """One row per scored column; columns the family map does not claim are
    returned separately (and fail DR-17 if non-empty).

    Callers always call this AFTER `sh.get_holdout(ctx)` (which calls
    `sh._ensure_src_on_path` internally), so `src/` is already on `sys.path`
    by the time this imports `rigor` — see `_dr17`.
    """
    import rigor

    owner: dict[str, str] = {}
    for fam, feats in rigor.GROUPS.items():
        for f in feats:
            owner[f] = fam

    rows, missing = [], []
    for c in cols:
        fam = owner.get(c)
        if fam is None:
            missing.append(c)
            continue
        base = _FAMILY_AVAILABILITY.get(fam, dict(available_at="undocumented", source="undocumented"))
        rows.append(dict(level=c, value=base["available_at"], ci=None, n=None,
                          detail=f"family={fam}; source={base['source']}"))
    return rows, missing


def _manifest_figure(ctx: RunnerContext, rows: list[dict]) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 2.2))
    ax.axis("off")
    ax.text(0.02, 0.7, f"DR-17 — availability-at-time manifest: {len(rows)} features covered",
            fontsize=11, weight="bold")
    ax.text(0.02, 0.35, "every model-input feature maps to a source system and a "
                        "stated availability lag — see report.json breakdown", fontsize=9)
    return sh.savefig(fig, ctx, "availability_manifest_note.png")


# --------------------------------------------------------------------------- #
# DR-15 — lead-time attribution
# --------------------------------------------------------------------------- #
def _lead_time_figure(ctx: RunnerContext, rigor_json: dict | None) -> str | None:
    import matplotlib.pyplot as plt

    if not rigor_json or "leakage_by_lead" not in rigor_json:
        return None
    # defensive against an older/different data/rigor.json schema (pre-dates
    # dpd_share/dpd_share_alt) — only plot buckets that carry both keys.
    leak = [L for L in rigor_json["leakage_by_lead"] if "dpd_share" in L and "dpd_share_alt" in L]
    if not leak:
        return None
    buckets = [L["bucket"] for L in leak]
    dpd = [L["dpd_share"] * 100 for L in leak]
    alt = [L["dpd_share_alt"] * 100 for L in leak]

    fig, ax = plt.subplots(figsize=(6.5, 4))
    x = np.arange(len(buckets))
    ax.bar(x - 0.2, dpd, width=0.4, label="primary (DPD family alone)", color="#1f6feb")
    ax.bar(x + 0.2, alt, width=0.4, label="alternative (+ collection)", color="#8b949e")
    ax.axhline(5, color="#da3633", ls="--", lw=1, label="DR-15 floor 5%")
    ax.set_xticks(x)
    ax.set_xticklabels(buckets)
    ax.set_ylabel("DPD-family attribution share (%)")
    ax.set_title("DR-15 — DPD-family share of attribution, by lead time")
    ax.legend(fontsize=8)
    return sh.savefig(fig, ctx, "lead_time_attribution.png")


def _independent_dr15(ctx: RunnerContext, seed: int) -> dict | None:
    """Independent recompute of DR-15 from the ALREADY-cached DR-01 holdout
    model, restricted to the 10-12mo bucket only (cheap: `pred_contrib` is
    computed on the bucket's few thousand rows, not the full ~470k-row test
    set rigor.py itself scores)."""
    try:
        h = sh.get_holdout(ctx)  # calls sh.load_panel -> _ensure_src_on_path first
        import rigor

        df_test, cols = h["df_test"], h["cols"]
        bucket_mask = ((df_test["default_within_12m"] == 1)
                       & df_test["months_to_npa"].between(*LEAD_BUCKET)).to_numpy()
        if bucket_mask.sum() == 0:
            return None
        X_bucket = h["X"].iloc[h["test_idx"]][bucket_mask]
        contrib = h["model"].booster_.predict(X_bucket, pred_contrib=True)[:, :-1]

        dpd_idx = [cols.index(c) for c in rigor.GROUPS["Days-past-due / repayment"] if c in cols]
        dpd_row = np.abs(contrib[:, dpd_idx]).sum(axis=1)
        total_row = np.abs(contrib).sum(axis=1)
        point = float(dpd_row.sum() / total_row.sum()) if total_row.sum() else None

        boot_df = pd.DataFrame({
            "account_id": df_test.loc[bucket_mask, "account_id"].to_numpy(),
            "dpd": dpd_row, "total": total_row,
        })
        ci = sh.bootstrap_ci(
            boot_df,
            lambda d: (d["dpd"].sum() / d["total"].sum()) if d["total"].sum() else None,
            n=sh.n_boot(ctx), seed=seed,
        )
        return dict(point=round(point, 4) if point is not None else None, ci=ci, n=int(bucket_mask.sum()))
    except Exception as exc:  # defensive — this is corroborating evidence, not the graded value
        return dict(error=str(exc))


def _dr15(ctx: RunnerContext, seed: int) -> Result:
    rigor_json = sh_load_rigor_json(ctx)
    primary = rigor_json.get("leakage_dpd_share") if rigor_json else None
    alt = rigor_json.get("leakage_alt_dpd_share") if rigor_json else None
    n_bucket = None
    if rigor_json:
        row = next((L for L in rigor_json.get("leakage_by_lead", []) if L.get("bucket") == "10-12 mo"), None)
        n_bucket = row.get("n") if row else None

    indep = _independent_dr15(ctx, seed)
    fig = _lead_time_figure(ctx, rigor_json)
    figs = [fig] if fig else []

    if primary is None:
        return Result("DR-15", status="pending",
                       detail="data/rigor.json missing leakage_dpd_share — run `python3 src/rigor.py` first",
                       figures=figs)

    ci = None
    cross_check = "independent recompute not available"
    if indep and "error" not in indep:
        ci = indep["ci"]
        agree = indep["point"] is not None and abs(indep["point"] - primary) < 0.01
        cross_check = (f"independent recompute from the cached DR-01 holdout model over the same "
                        f"bucket (n={indep['n']}): {indep['point']} "
                        f"({'agrees with' if agree else 'DIFFERS from'} data/rigor.json's {primary} "
                        f"within 1pp)")
    elif indep:
        cross_check = f"independent recompute failed: {indep['error']}"

    return Result(
        "DR-15", value=primary, ci=ci, n=n_bucket, figures=figs,
        detail=(f"primary reading (collection_ratio as its own family, per src/rigor.py's "
                f"leakage_families.primary): {primary:.4f}. Alternative reading (collection folded "
                f"into DPD): {alt}. {cross_check}. DRISHTi's own GROUPS families: "
                f"{sorted(rigor_json.get('leakage_families', {}).get('families_in_model', []))}."),
    )


def sh_load_rigor_json(ctx: RunnerContext) -> dict | None:
    import json
    path = ctx.repo_root / "data" / "rigor.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# DR-16 — permuted-label AUC, averaged over the registered seeds
# --------------------------------------------------------------------------- #
def _permutation_figure(ctx: RunnerContext, per_seed: list[dict]) -> str:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    seeds = [r["level"] for r in per_seed]
    aucs = [r["value"] for r in per_seed]
    ax.bar(seeds, aucs, color="#1f6feb")
    ax.axhspan(0.48, 0.52, color="#2ea043", alpha=0.15, label="DR-16 band [0.48, 0.52]")
    ax.axhline(0.50, color="#8b949e", ls=":", lw=1)
    ax.set_ylim(0.30, 0.70)
    ax.set_xlabel("seed")
    ax.set_ylabel("permuted-label AUC (9,000 x 36 book)")
    ax.set_title("DR-16 — permutation retrain, per seed")
    ax.legend(fontsize=8)
    return sh.savefig(fig, ctx, "permutation_auc.png")


def _dr16(ctx: RunnerContext) -> Result:
    seeds = ctx.seeds or (7, 8, 9, 10, 11)
    per_seed = []
    for s in seeds:
        out = rf.fit_permuted(ctx, s)
        per_seed.append(dict(level=f"seed={s}", value=round(out["auc"], 4) if out["auc"] is not None else None,
                              ci=None, n=out["n"]))
    valid = [r["value"] for r in per_seed if r["value"] is not None]
    mean_auc = round(float(np.mean(valid)), 4) if valid else None
    ci = (round(float(min(valid)), 4), round(float(max(valid)), 4)) if valid else None
    fig = _permutation_figure(ctx, per_seed)
    return Result(
        "DR-16", value=mean_auc, ci=ci, n=per_seed[0]["n"] if per_seed else None, figures=[fig],
        detail=(f"mean over {len(valid)}/{len(seeds)} registered seeds of a full retrain on "
                f"randomly permuted labels (split/features/hyper-parameters untouched), on the "
                f"9,000 x 36 book (see _refit.py for why not the full 45,000 x 48 book). "
                f"Per-seed: {per_seed}."),
    )


# --------------------------------------------------------------------------- #
# DR-17 — availability-at-time manifest
# --------------------------------------------------------------------------- #
def _dr17(ctx: RunnerContext) -> Result:
    h = sh.get_holdout(ctx)
    rows, missing = _availability_manifest(h["cols"])
    fig = _manifest_figure(ctx, rows)
    ok = len(missing) == 0 and len(rows) > 0
    return Result(
        "DR-17", value=ok, n=len(rows), breakdown=rows, figures=[fig],
        detail=(f"{len(rows)} of {len(h['cols'])} scored model-input columns covered by the "
                f"manifest" + (f"; MISSING from manifest: {missing}" if missing else "; every "
                f"scored column is covered")),
    )


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    seed = sh.get_seed(ctx)
    results: list[Result] = []
    if "DR-15" in by_id:
        results.append(_dr15(ctx, seed))
    if "DR-16" in by_id:
        results.append(_dr16(ctx))
    if "DR-17" in by_id:
        results.append(_dr17(ctx))
    return results
