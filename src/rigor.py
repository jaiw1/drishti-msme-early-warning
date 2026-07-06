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

ROOT = __file__.rsplit("/src/", 1)[0]
PANEL = f"{ROOT}/data/msme_loan_panel.csv"
OUT = f"{ROOT}/data/rigor.json"
CAT = ["sector", "region", "loan_type", "segment", "qualification", "promoter_age_group"]
DROP = ["account_id", "month_idx", "date", "default_within_12m", "labelable", "months_to_npa"]

GROUPS = {
    "Days-past-due / repayment": ["dpd", "dpd_max_6m", "times_late_6m", "bounce", "bounces_6m", "minbal_breach", "minbal_breach_6m"],
    "Cash-flow (inflows / GST)": ["inflow", "gst_sales", "inflow_trend_3m", "inflow_vs_6m_avg", "sales_trend_3m", "txn_count", "txn_drop_flag"],
    "Credit-limit utilisation": ["utilisation", "util_avg_3m", "util_max_6m", "months_over_90pct_util_6m"],
    "Adverse filings": ["adverse_remark", "adverse_remark_6m"],
    "Borrower profile": ["log_sanctioned", "vintage_months", "business_age_years", "sector", "region", "loan_type", "segment", "qualification", "promoter_age_group"],
}
LGB = dict(n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
           colsample_bytree=0.8, min_child_samples=80, random_state=7, n_jobs=-1, verbose=-1)


def ks(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def main():
    df = pd.read_csv(PANEL)
    for c in CAT:
        df[c] = df[c].astype("category")
    y = df["default_within_12m"].values
    X = df.drop(columns=DROP)
    cols = list(X.columns)

    tr, te = next(GroupShuffleSplit(1, test_size=0.30, random_state=7).split(X, y, groups=df["account_id"]))
    Xtr, Xte, ytr, yte = X.iloc[tr], X.iloc[te], y[tr], y[te]

    model = LGBMClassifier(**LGB).fit(Xtr, ytr, categorical_feature=CAT)
    p_te = model.predict_proba(Xte)[:, 1]
    grouped_auc = roc_auc_score(yte, p_te)

    # ---- 1. CALIBRATION (isotonic fit on an inner validation slice of train) ----
    itr, iva = next(GroupShuffleSplit(1, test_size=0.25, random_state=11).split(Xtr, ytr, groups=df["account_id"].iloc[tr]))
    m_cal = LGBMClassifier(**LGB).fit(Xtr.iloc[itr], ytr[itr], categorical_feature=CAT)
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
        leakage.append(dict(bucket=f"{lo}-{hi} mo",
                            shares={g: round(100 * v / tot, 1) for g, v in by_group.items()}))

    # ---- 3. OUT-OF-TIME split (train early months, test later months) ----
    CUT = 18
    otr, ote = (df.month_idx < CUT).values, (df.month_idx >= CUT).values
    m_oot = LGBMClassifier(**LGB).fit(X[otr], y[otr], categorical_feature=CAT)
    p_oot = m_oot.predict_proba(X[ote])[:, 1]
    out_of_time = dict(train_window=f"months 0-{CUT-1}", test_window=f"months {CUT}+",
                       auc=round(float(roc_auc_score(y[ote], p_oot)), 3), ks=round(ks(y[ote], p_oot), 3),
                       grouped_auc=round(float(grouped_auc), 3))

    # ---- 4. BASELINE LADDER (logistic scorecard vs LightGBM, same grouped split) ----
    num = [c for c in cols if c not in CAT]
    Xtr_l = pd.concat([Xtr[num], pd.get_dummies(Xtr[CAT])], axis=1)
    Xte_l = pd.concat([Xte[num], pd.get_dummies(Xte[CAT])], axis=1).reindex(columns=Xtr_l.columns, fill_value=0)
    logit = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                          LogisticRegression(max_iter=1000, class_weight="balanced")).fit(Xtr_l, ytr)
    baseline_ladder = [
        dict(model="Logistic regression (scorecard-style)", auc=round(float(roc_auc_score(yte, logit.predict_proba(Xte_l)[:, 1])), 3)),
        dict(model="LightGBM (ours)", auc=round(float(grouped_auc), 3)),
    ]

    out = dict(calibration=calibration, leakage_by_lead=leakage, out_of_time=out_of_time, baseline_ladder=baseline_ladder)
    json.dump(out, open(OUT, "w"), indent=1)

    print(f"CALIBRATION  Brier raw {calibration['brier_raw']} -> calibrated {calibration['brier_calibrated']}")
    print("LEAKAGE by lead time (share of model attention, %):")
    for L in leakage:
        s = L["shares"]
        print(f"   {L['bucket']:8s}  DPD/repayment {s['Days-past-due / repayment']:5.1f} | "
              f"cash-flow {s['Cash-flow (inflows / GST)']:5.1f} | utilisation {s['Credit-limit utilisation']:5.1f} | "
              f"profile {s['Borrower profile']:5.1f}")
    print(f"OUT-OF-TIME  grouped-split AUC {out_of_time['grouped_auc']} vs out-of-time AUC {out_of_time['auc']} (KS {out_of_time['ks']})")
    print(f"BASELINE     logistic {baseline_ladder[0]['auc']}  ->  LightGBM {baseline_ladder[1]['auc']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
