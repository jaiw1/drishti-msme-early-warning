"""
Baseline early-warning model + HONEST metrics  —  sanity check on the synthetic panel.

Purpose right now: prove the dataset is (a) realistic (AUC in a believable band, not ~0.99),
and (b) that the LEADING signals (cash-flow/utilisation trends) — not just current DPD —
carry the prediction, which is the whole "we saw it a year early" thesis.

Split is GROUPED BY ACCOUNT (no account appears in both train and test) to avoid leakage.
Metrics reported the way a banker cares about them, NOT raw accuracy:
  ROC-AUC, PR-AUC, KS, and recall@review-budget (if officers review the riskiest X% each month,
  what share of true 12-month defaults do we catch?).
"""

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import roc_auc_score, average_precision_score, roc_curve

DATA = __file__.rsplit("/src/", 1)[0] + "/data/msme_loan_panel.csv"
CAT = ["sector", "region", "loan_type", "segment", "qualification", "promoter_age_group"]
DROP = ["account_id", "month_idx", "date", "default_within_12m", "labelable", "months_to_npa"]


def recall_at_budget(y, p, budget):
    """If we flag the top `budget` fraction by risk, what share of true defaults do we catch?"""
    k = max(1, int(len(p) * budget))
    idx = np.argsort(p)[::-1][:k]
    return y[idx].sum() / max(1, y.sum())


def ks_stat(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def main():
    df = pd.read_csv(DATA)
    for c in CAT:
        df[c] = df[c].astype("category")
    y = df["default_within_12m"].values
    X = df.drop(columns=DROP)

    gss = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=7)
    tr, te = next(gss.split(X, y, groups=df["account_id"]))
    Xtr, Xte, ytr, yte = X.iloc[tr], X.iloc[te], y[tr], y[te]

    # same config as export_demo.py / rigor.py so every script reports the same model
    model = LGBMClassifier(
        n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
        colsample_bytree=0.8, min_child_samples=80,
        random_state=7, n_jobs=-1, verbose=-1,
    )
    model.fit(Xtr, ytr, categorical_feature=CAT)
    p = model.predict_proba(Xte)[:, 1]

    print("=" * 64)
    print(f"rows: train {len(ytr):,} / test {len(yte):,}   test default prevalence {yte.mean():.2%}")
    print("=" * 64)
    print(f"ROC-AUC : {roc_auc_score(yte, p):.3f}   (target believable band 0.85-0.93)")
    print(f"PR-AUC  : {average_precision_score(yte, p):.3f}   (baseline = prevalence {yte.mean():.3f})")
    print(f"KS      : {ks_stat(yte, p):.3f}")
    print("-" * 64)
    print("Recall @ officer review budget (the metric bankers actually act on):")
    for b in (0.02, 0.05, 0.10, 0.20):
        print(f"   top {b:4.0%} riskiest flagged -> catch {recall_at_budget(yte, p, b):5.1%} of true 12-month defaults")
    print("-" * 64)
    imp = pd.Series(model.feature_importances_, index=X.columns).sort_values(ascending=False)
    print("Top 12 features driving the prediction:")
    for k, v in imp.head(12).items():
        print(f"   {k:26s} {int(v)}")
    # ---- LEAD-TIME story (the hero) ----
    te_df = df.iloc[te].copy()
    te_df["p"] = p
    thr = np.quantile(p, 0.90)                       # top-10% monthly review budget -> a "flag"
    te_df["flagged"] = te_df["p"] >= thr

    print("-" * 64)
    print("Recall by LEAD TIME (row-level, at top-10% review budget):")
    print("   how many months before NPA can we catch it?")
    for lo, hi in [(1, 3), (4, 6), (7, 9), (10, 12)]:
        m = (te_df.default_within_12m == 1) & te_df.months_to_npa.between(lo, hi)
        if m.sum():
            print(f"   {lo:2d}-{hi:2d} months out : catch {te_df.loc[m, 'flagged'].mean():5.1%} of these")

    # account-level: for each defaulter we ever flag, how EARLY was the first flag?
    defs = te_df[te_df.default_within_12m == 1]
    per_acct = te_df[te_df.flagged].groupby("account_id").months_to_npa.max()   # earliest warning per acct
    caught_ids = set(per_acct.index)
    all_def_ids = set(defs.account_id.unique())
    print("-" * 64)
    print(f"Of {len(all_def_ids)} test accounts destined to default, we raise an early flag on "
          f"{len(caught_ids & all_def_ids)} ({len(caught_ids & all_def_ids)/max(1,len(all_def_ids)):.0%}).")
    lead = per_acct.loc[list(caught_ids & all_def_ids)]
    print(f"   first-warning lead time: median {lead.median():.0f} mo | "
          f">=6mo ahead {np.mean(lead>=6):.0%} | >=9mo {np.mean(lead>=9):.0%} | >=12mo {np.mean(lead>=12):.0%}")


if __name__ == "__main__":
    main()
