"""
Model-risk RIGOR pack  ->  data/rigor.json  (the evidence a bank risk reviewer asks for)

Four checks, all on the synthetic panel:
  1. CALIBRATION   — isotonic calibration + reliability curve + Brier (raw vs calibrated).
                     Makes "PD = 40%" mean an actual 40% observed default frequency.
  2. LEAKAGE / lead-time attribution — proves the LONG-lead (7-12 mo) warnings are driven by
                     CASH-FLOW / UTILISATION, NOT by the near-term days-past-due feature.
                     This is what makes the "we see it a year early" claim honest.
  3. OUT-OF-TIME   — train on early calendar months, test on later ones (temporal generalisation),
                     not just a random/grouped split.
  4. BASELINE LADDER — logistic-regression scorecard vs our LightGBM, so the gain is contextualised.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, roc_curve, brier_score_loss

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so `generator` imports

from generator.build import PANEL_COLUMNS   # noqa: E402  (path shim must run first)

ROOT = __file__.rsplit("/src/", 1)[0]
PANEL = f"{ROOT}/data/msme_loan_panel.csv"
OUT = f"{ROOT}/data/rigor.json"
# The five SD-D2 statics are categorical; without them LightGBM refuses the panel
# ("pandas dtypes must be int, float or bool").  Kept identical to export_demo.py's list.
CAT = ["sector", "region", "loan_type", "segment", "qualification", "promoter_age_group"]
CAT += ["portfolio", "constitution", "state", "city_tier", "nic_group"]
# SD-D8: a bank-style vintage bucket, scored in place of the raw month counter
# below — see export_demo.py's matching CAT/DROP note (kept identical, always).
CAT += ["vintage_band"]
# Every FORWARD-LOOKING column is dropped here or the model trains on the answer.
# `sma2_within_6m` (SD-D5) is a label, not a feature: it says whether the account
# reaches 61-90 DPD in the NEXT six months. A test pins this list against the
# generator's own declaration, so a label added later cannot slip into training.
# SD-D8: `vintage_months` also drops out of the feature set (not the CSV) — it
# drifts by construction under any time-split OOT (DR-14's binding max-CSI
# feature); `vintage_band` above is the model's replacement.
DROP = ["account_id", "month_idx", "date", "vintage_months",
        "default_within_12m", "sma2_within_6m", "labelable", "months_to_npa"]

# --------------------------------------------------------------------------- #
# Feature FAMILIES for the leakage attribution.  Every scored column must belong to
# exactly one family, or its attribution silently vanishes from the denominator and
# the DPD share reported against DR-15 is flattering rather than true; a test asserts
# the mapping is total.
#
# "Demand vs collection" IS ITS OWN FAMILY, and that is a judgement call, not an
# accident of grouping.  `collection_ratio` measures how much of the amount demanded
# actually arrived — money, not lateness — and it leads arrears by 5-8 months across
# the eight portfolios.  Folding it into the days-past-due family instead would move
# the 10-12 month DPD attribution from ~1% to ~11% and fail DR-15.  Because the whole
# early-warning claim rests on which side of that line it falls, BOTH readings are
# computed and emitted (`leakage_dpd_share` and `leakage_alt_dpd_share`), so the model
# card and the honesty gate can show the number under either convention rather than
# inheriting ours silently.
# --------------------------------------------------------------------------- #
DPD_FAMILY = "Days-past-due / repayment"
COLLECTION_FAMILY = "Demand vs collection"
GROUPS = {
    DPD_FAMILY: ["dpd", "dpd_max_6m", "times_late_6m", "bounce", "bounces_6m", "minbal_breach", "minbal_breach_6m"],
    "Cash-flow (inflows / GST)": ["inflow", "gst_sales", "inflow_trend_3m", "inflow_vs_6m_avg", "sales_trend_3m", "txn_count", "txn_drop_flag"],
    COLLECTION_FAMILY: ["demanded_amount", "collected_amount", "collection_ratio", "collection_ratio_3m"],
    "Credit-limit utilisation": ["utilisation", "util_avg_3m", "util_max_6m", "months_over_90pct_util_6m", "drawing_power", "outstanding"],
    "Income & balance": ["salary_credit", "salary_vs_6m_avg", "salary_gap_6m", "balance", "min_balance_6m",
                         "rental_income", "rental_vs_6m_avg", "crop_receipt", "crop_receipt_vs_norm",
                         "commute_spend", "commute_vs_6m_avg"],
    "Leverage & collateral": ["other_bank_emi", "emi_burden_ratio", "ltv", "ltv_vs_schedule",
                              "renewal_overdue_months", "moratorium_active", "months_since_moratorium_end"],
    "Bureau": ["bureau_score"],
    "Adverse filings": ["adverse_remark", "adverse_remark_6m"],
    # SD-D8: `vintage_months` moved to DROP (not scored) in favour of the
    # `vintage_band` categorical, which is scored and familied here instead.
    "Borrower profile": ["log_sanctioned", "vintage_band", "business_age_years", "sector", "region",
                         "loan_type", "segment", "qualification", "promoter_age_group",
                         "portfolio", "constitution", "state", "city_tier", "nic_group",
                         "secured", "tenor_months", "interest_rate_pa"],
}
#: the alternative reading: collection folded into days-past-due
ALT_DPD_FAMILIES = (DPD_FAMILY, COLLECTION_FAMILY)
#: the lead bucket DR-15 is measured in
LEAKAGE_BUCKET = "10-12 mo"
LGB = dict(n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
           colsample_bytree=0.8, min_child_samples=80, random_state=7, n_jobs=-1, verbose=-1)


def unfamilied_columns(columns=None):
    """Scored columns that no family claims — must always be empty.

    Args:
        columns: panel columns to check; defaults to the generator's own column list.

    Returns:
        Sorted list of orphan column names.
    """
    familied = {f for feats in GROUPS.values() for f in feats}
    scored = set(columns if columns is not None else PANEL_COLUMNS) - set(DROP)
    return sorted(scored - familied)


def ks(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def main():
    df = pd.read_csv(PANEL)
    cats = [c for c in CAT if c in df.columns]
    for c in cats:
        df[c] = df[c].astype("category")
    y = df["default_within_12m"].values
    X = df.drop(columns=DROP)
    cols = list(X.columns)
    orphans = unfamilied_columns(cols)
    if orphans:
        raise AssertionError(
            "leakage attribution would silently drop these columns — give each one a "
            f"family in GROUPS: {orphans}")

    tr, te = next(GroupShuffleSplit(1, test_size=0.30, random_state=7).split(X, y, groups=df["account_id"]))
    Xtr, Xte, ytr, yte = X.iloc[tr], X.iloc[te], y[tr], y[te]

    model = LGBMClassifier(**LGB).fit(Xtr, ytr, categorical_feature=cats)
    p_te = model.predict_proba(Xte)[:, 1]
    grouped_auc = roc_auc_score(yte, p_te)

    # ---- 1. CALIBRATION (isotonic fit on an inner validation slice of train) ----
    itr, iva = next(GroupShuffleSplit(1, test_size=0.25, random_state=11).split(Xtr, ytr, groups=df["account_id"].iloc[tr]))
    m_cal = LGBMClassifier(**LGB).fit(Xtr.iloc[itr], ytr[itr], categorical_feature=cats)
    iso = IsotonicRegression(out_of_bounds="clip").fit(m_cal.predict_proba(Xtr.iloc[iva])[:, 1], ytr[iva])
    p_raw = m_cal.predict_proba(Xte)[:, 1]
    p_cal = iso.predict(p_raw)
    q = pd.qcut(p_raw, 10, duplicates="drop")
    rel = pd.DataFrame({"p_raw": p_raw, "p_cal": p_cal, "y": yte, "bin": q}).groupby("bin", observed=True).agg(
        pred_raw=("p_raw", "mean"), pred_cal=("p_cal", "mean"), obs=("y", "mean"), n=("y", "size")).reset_index(drop=True)
    calibration = dict(
        brier_raw=round(float(brier_score_loss(yte, p_raw)), 4),
        brier_calibrated=round(float(brier_score_loss(yte, p_cal)), 4),
        reliability=[dict(pred=round(r.pred_cal, 3), obs=round(r.obs, 3), n=int(r.n)) for r in rel.itertuples()],
    )

    # ---- 2. LEAKAGE / lead-time attribution (SHAP-style feature contributions) ----
    contrib = np.abs(model.booster_.predict(Xte, pred_contrib=True)[:, :-1])
    te_df = df.iloc[te].reset_index(drop=True)
    leakage = []
    for lo, hi in [(1, 3), (4, 6), (7, 9), (10, 12)]:
        mask = (te_df.default_within_12m == 1) & te_df.months_to_npa.between(lo, hi)
        if not mask.any():
            continue
        mean_contrib = contrib[mask.values].mean(axis=0)
        by_group = {g: float(sum(mean_contrib[cols.index(f)] for f in feats if f in cols)) for g, feats in GROUPS.items()}
        tot = sum(by_group.values()) or 1.0
        shares = {g: round(100 * v / tot, 1) for g, v in by_group.items()}
        # DR-15 is measured on the DPD family's share.  Both readings of where
        # "demand vs collection" belongs are carried, at every lead bucket.
        dpd_share = by_group[DPD_FAMILY] / tot
        alt_share = sum(by_group[g] for g in ALT_DPD_FAMILIES) / tot
        leakage.append(dict(bucket=f"{lo}-{hi} mo", n=int(mask.sum()), shares=shares,
                            dpd_share=round(dpd_share, 4),
                            dpd_share_alt=round(alt_share, 4)))

    at_bucket = next((L for L in leakage if L["bucket"] == LEAKAGE_BUCKET), None)
    leakage_families = dict(
        bucket=LEAKAGE_BUCKET,
        primary=dict(
            families=[DPD_FAMILY],
            share=at_bucket["dpd_share"] if at_bucket else None,
            reading=("`collection_ratio` is its own family: it measures money arriving, not "
                     "days late, and it leads arrears by 5-8 months across the eight "
                     "portfolios. This is the reading DR-15 is scored against."),
        ),
        alternative=dict(
            families=list(ALT_DPD_FAMILIES),
            share=at_bucket["dpd_share_alt"] if at_bucket else None,
            reading=("`collection_ratio` folded into days-past-due, on the argument that a "
                     "short collection IS the arrear one month before it is one. Reported so "
                     "the choice is visible rather than inherited."),
        ),
        criterion="DR-15: DPD-family attribution share at 10-12 months must be <= 0.05",
        families_in_model=sorted(GROUPS),
    )

    # ---- 3. OUT-OF-TIME split (train early months, test later months) ----
    CUT = 18
    otr, ote = (df.month_idx < CUT).values, (df.month_idx >= CUT).values
    m_oot = LGBMClassifier(**LGB).fit(X[otr], y[otr], categorical_feature=cats)
    p_oot = m_oot.predict_proba(X[ote])[:, 1]
    out_of_time = dict(train_window=f"months 0-{CUT-1}", test_window=f"months {CUT}+",
                       auc=round(float(roc_auc_score(y[ote], p_oot)), 3), ks=round(ks(y[ote], p_oot), 3),
                       grouped_auc=round(float(grouped_auc), 3))

    # ---- 4. BASELINE LADDER (logistic scorecard vs LightGBM, same grouped split) ----
    num = [c for c in cols if c not in cats]
    Xtr_l = pd.concat([Xtr[num], pd.get_dummies(Xtr[cats])], axis=1)
    Xte_l = pd.concat([Xte[num], pd.get_dummies(Xte[cats])], axis=1).reindex(columns=Xtr_l.columns, fill_value=0)
    logit = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                          LogisticRegression(max_iter=1000, class_weight="balanced")).fit(Xtr_l, ytr)
    baseline_ladder = [
        dict(model="Logistic regression (scorecard-style)", auc=round(float(roc_auc_score(yte, logit.predict_proba(Xte_l)[:, 1])), 3)),
        dict(model="LightGBM (ours)", auc=round(float(grouped_auc), 3)),
    ]

    out = dict(
        calibration=calibration, leakage_by_lead=leakage, leakage_families=leakage_families,
        leakage_dpd_share=leakage_families["primary"]["share"],
        leakage_alt_dpd_share=leakage_families["alternative"]["share"],
        out_of_time=out_of_time, baseline_ladder=baseline_ladder,
    )
    with open(OUT, "w") as f:
        # allow_nan=False: bare NaN is not JSON, and this file is embedded whole into
        # demo_data.json, which the cockpit parses in the browser.
        json.dump(out, f, indent=1, allow_nan=False)

    print(f"CALIBRATION  Brier raw {calibration['brier_raw']} -> calibrated {calibration['brier_calibrated']}")
    print(f"FAMILIES     {len(GROUPS)} families, 0 unfamilied columns of {len(cols)} scored")
    print("LEAKAGE by lead time (share of model attention, %):")
    for L in leakage:
        s = L["shares"]
        print(f"   {L['bucket']:8s} n={L['n']:<6d} " + " | ".join(
            f"{g.split(' (')[0].split(' / ')[0].lower()} {s[g]:5.1f}" for g in sorted(GROUPS)))
    print(f"DR-15        DPD share at {LEAKAGE_BUCKET}: primary {out['leakage_dpd_share']:.3%} "
          f"(collection as its own family) | alternative {out['leakage_alt_dpd_share']:.3%} "
          f"(collection folded into DPD)  [threshold 5%]")
    print(f"OUT-OF-TIME  grouped-split AUC {out_of_time['grouped_auc']} vs out-of-time AUC {out_of_time['auc']} (KS {out_of_time['ks']})")
    print(f"BASELINE     logistic {baseline_ladder[0]['auc']}  ->  LightGBM {baseline_ladder[1]['auc']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
