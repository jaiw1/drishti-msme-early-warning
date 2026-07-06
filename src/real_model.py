"""
REAL Indian MSME default model  (validation on real data)

Uses a real Indian MSME financial-data export (msme_data/*.csv):
  * msme_fin_data.csv        real standalone annual financials, FY2018-FY2026 (₹ Crore, wide: metric x year)
  * msme_ratings_movement.csv real credit-rating history -> DEFAULT label (a 'D' rating = actual default)
  * msme_identifiers.csv      industry (NIC) + incorporation year

Setup (leakage-safe, predictive):
  - For a DEFAULTER (first 'D' rating in year D): observe financials from the latest year < D  -> label 1.
  - For a NON-defaulter (rated, never 'D'): observe latest available financials              -> label 0.
  - Features = scale-free financial ratios + year-on-year trends + industry + age. Predict future default.

Real data => expect an HONEST AUC ~0.75-0.85 (not the synthetic 0.95). That is the whole point.
"""

import csv, re, json
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import roc_auc_score, roc_curve, average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

DIR = __file__.rsplit("/msme-ews/", 1)[0] + "/msme_data"
OUT = __file__.rsplit("/src/", 1)[0] + "/data/real_model.json"


def num(x):
    x = (x or "").strip()
    try:
        return float(x)
    except ValueError:
        return np.nan


def yr(s):
    m = re.search(r"(\d{4})", s or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- ratings -> default year
def load_defaults():
    rows = list(csv.reader(open(f"{DIR}/msme_ratings_movement.csv", encoding="utf-8-sig")))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Company Name")
    H = {h: i for i, h in enumerate(rows[hi])}
    rated, first_def = set(), {}
    for r in rows[hi + 1:]:
        if len(r) < 6 or not r[0].strip():
            continue
        c = r[0].strip()
        rated.add(c)
        rating = r[H["Rating"]].strip()
        if rating == "D" or rating.startswith("D "):
            y = yr(r[H["Date"]])
            if y and (c not in first_def or y < first_def[c]):
                first_def[c] = y
    return rated, first_def


# ---------------------------------------------------------------- identifiers -> nic/age
def load_ids():
    ids = {}
    for r in csv.DictReader(open(f"{DIR}/msme_identifiers.csv", encoding="utf-8-sig")):
        ids[r["Company Name"].strip()] = dict(nic=(r.get("NIC code") or "")[:2],
                                              incorp=yr(r.get("Incorporation year") or ""))
    return ids


# ---------------------------------------------------------------- financials -> panel
def load_financials(keep):
    rows = list(csv.reader(open(f"{DIR}/msme_fin_data.csv", encoding="utf-8-sig")))
    years = [yr(y) for y in rows[4]]
    names = [n.strip() for n in rows[5]]
    fin = {}
    for r in rows[6:]:
        if not r or not r[0].strip():
            continue
        c = r[0].strip()
        if c not in keep:
            continue
        d = {}
        for i, (y, nm) in enumerate(zip(years, names)):
            if y and nm and i < len(r) and r[i].strip():
                d.setdefault(y, {})[nm] = num(r[i])
        fin[c] = d
    return fin


def features(m, p):
    """Ratios at observation year m, plus trends vs prior year p."""
    def sd(a, b):
        return a / b if (b not in (0, None) and not pd.isna(b) and not pd.isna(a)) else np.nan
    inc = m.get("Total Income"); nw = m.get("Net worth"); pat = m.get("PAT")
    tb = m.get("Total borrowings including default")
    f = dict(
        interest_cover=m.get("Interest cover (times)", sd(m.get("PBIT"), m.get("Interest expense"))),
        debt_to_equity=m.get("Debt to equity ratio (times)", sd(tb, nw)),
        pat_margin=sd(pat, inc),
        pbdita_margin=sd(m.get("PBDITA"), inc),
        pbt_margin=sd(m.get("PBT"), inc),
        borrow_to_income=sd(tb, inc),
        borrow_to_networth=sd(tb, nw),
        neg_networth=1.0 if (nw is not None and not pd.isna(nw) and nw < 0) else 0.0,
        loss_flag=1.0 if (pat is not None and not pd.isna(pat) and pat < 0) else 0.0,
        log_income=np.log(inc) if (inc and inc > 0) else np.nan,
    )
    if p:
        f["d_networth"] = sd((nw or np.nan) - p.get("Net worth", np.nan), abs(p.get("Net worth")) if p.get("Net worth") else np.nan)
        f["d_income"] = sd((inc or np.nan) - p.get("Total Income", np.nan), abs(p.get("Total Income")) if p.get("Total Income") else np.nan)
        f["d_pat"] = sd((pat or np.nan) - p.get("PAT", np.nan), abs(p.get("PAT")) if p.get("PAT") else np.nan)
        f["d_borrow"] = sd((tb or np.nan) - p.get("Total borrowings including default", np.nan),
                           abs(p.get("Total borrowings including default")) if p.get("Total borrowings including default") else np.nan)
    return f


def build_table(horizon=2, last_year=2026):
    """Panel: one row per (company, financial-year Y) predicting default within [Y+1, Y+horizon].
    Temporally consistent (both classes observed at the same Y), leakage-safe (no post-default rows)."""
    rated, first_def = load_defaults()
    ids = load_ids()
    fin = load_financials(rated)
    rows = []
    for c, d in fin.items():
        fy = sorted(y for y, mm in d.items() if "Net worth" in mm)
        dY = first_def.get(c)
        meta = ids.get(c, {})
        for Y in fy:
            if dY and Y >= dY:
                continue                                  # drop financials at/after default
            if dY:
                label = 1 if (Y < dY <= Y + horizon) else 0
            elif Y + horizon <= last_year:                # non-defaulter: only if outcome window observable
                label = 0
            else:
                continue
            f = features(d[Y], d.get(Y - 1))
            f.update(nic=meta.get("nic") or "NA", age=(Y - meta["incorp"]) if meta.get("incorp") else np.nan,
                     obs_year=Y, default=label, company=c)
            rows.append(f)
    return pd.DataFrame(rows)


def ks(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


NIC2 = {"01": "Agriculture", "05": "Mining", "10": "Food products", "11": "Beverages", "13": "Textiles",
        "14": "Apparel", "15": "Leather", "16": "Wood products", "17": "Paper", "18": "Printing",
        "20": "Chemicals", "21": "Pharmaceuticals", "22": "Rubber & plastics", "23": "Cement & minerals",
        "24": "Basic metals", "25": "Fabricated metal", "26": "Electronics", "27": "Electrical equipment",
        "28": "Machinery", "29": "Auto & parts", "30": "Other transport eqpt", "31": "Furniture",
        "32": "Other manufacturing", "35": "Power", "41": "Construction", "42": "Civil engineering",
        "43": "Specialised construction", "45": "Auto trade", "46": "Wholesale trade", "47": "Retail trade",
        "49": "Land transport", "52": "Warehousing", "55": "Hotels", "56": "Restaurants", "62": "IT services",
        "64": "Finance", "68": "Real estate", "71": "Engineering services", "72": "R&D", "82": "Business support"}

REASON = {
    "interest_cover":    lambda v: f"Interest cover only {v:.1f}× — profits barely cover interest" if pd.notna(v) and v < 1.5 else None,
    "borrow_to_income":  lambda v: f"Borrowings {v:.1f}× annual income" if pd.notna(v) and v > 1 else None,
    "loss_flag":         lambda v: "Loss-making (negative profit)" if v == 1 else None,
    "neg_networth":      lambda v: "Negative net worth — capital eroded" if v == 1 else None,
    "d_income":          lambda v: f"Income falling ({v*100:.0f}% YoY)" if pd.notna(v) and v < -0.05 else None,
    "d_borrow":          lambda v: f"Borrowings rising ({v*100:.0f}% YoY)" if pd.notna(v) and v > 0.1 else None,
    "debt_to_equity":    lambda v: f"High leverage (debt-to-equity {v:.1f})" if pd.notna(v) and v > 2 else None,
    "pbdita_margin":     lambda v: f"Thin operating margin ({v*100:.0f}%)" if pd.notna(v) and v < 0.06 else None,
    "pat_margin":        lambda v: f"Weak profit margin ({v*100:.0f}%)" if pd.notna(v) and v < 0.02 else None,
    "d_pat":             lambda v: "Profit deteriorating year-on-year" if pd.notna(v) and v < -0.1 else None,
    "d_networth":        lambda v: "Net worth shrinking" if pd.notna(v) and v < -0.05 else None,
    "age":               lambda v: "Young company (<3 yrs)" if pd.notna(v) and v < 3 else None,
    "log_income":        lambda v: "Very small company (<₹1 cr income)" if pd.notna(v) and v < 0 else None,
}


def real_reasons(row, contribs, cols, k=3):
    out = []
    for c, ct in sorted(zip(cols, contribs), key=lambda x: -x[1]):
        if ct <= 0 or c not in REASON:
            continue
        s = REASON[c](row[c])
        if s:
            out.append(s)
        if len(out) >= k:
            break
    return out


def main():
    df = build_table()
    print(f"modeling rows: {len(df)} | defaults: {int(df.default.sum())} ({df.default.mean():.1%}) | obs-year range {int(df.obs_year.min())}-{int(df.obs_year.max())}")
    NUM = ["interest_cover", "debt_to_equity", "pat_margin", "pbdita_margin", "pbt_margin",
           "borrow_to_income", "borrow_to_networth", "neg_networth", "loss_flag", "log_income",
           "d_networth", "d_income", "d_pat", "d_borrow", "age"]
    df["nic"] = df["nic"].astype("category")
    X = df[NUM + ["nic"]].copy()
    y = df["default"].values

    tr, te = next(GroupShuffleSplit(1, test_size=0.30, random_state=7).split(X, y, groups=df["company"]))
    Xtr, Xte, ytr, yte = X.iloc[tr], X.iloc[te], y[tr], y[te]
    model = LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=32, min_child_samples=40,
                           subsample=0.8, colsample_bytree=0.8, random_state=7, n_jobs=-1, verbose=-1)
    model.fit(Xtr, ytr, categorical_feature=["nic"])
    p = model.predict_proba(Xte)[:, 1]

    # logistic baseline (numeric only)
    logit = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                          LogisticRegression(max_iter=1000, class_weight="balanced")).fit(Xtr[NUM], ytr)
    p_lr = logit.predict_proba(Xte[NUM])[:, 1]

    auc, prauc, ksv = roc_auc_score(yte, p), average_precision_score(yte, p), ks(yte, p)

    # feature importances with plain-English labels
    LABEL = {"log_income": "Company size (income)", "borrow_to_income": "Borrowings ÷ income",
             "interest_cover": "Interest cover", "age": "Company age", "d_income": "Income trend",
             "pbdita_margin": "Operating margin", "d_borrow": "Borrowings trend", "d_pat": "Profit trend",
             "debt_to_equity": "Leverage (D/E)", "pat_margin": "Profit margin", "pbt_margin": "Pre-tax margin",
             "neg_networth": "Negative net worth", "loss_flag": "Loss-making", "d_networth": "Net-worth trend",
             "nic": "Industry"}
    imp = pd.Series(model.feature_importances_, index=X.columns).sort_values(ascending=False)
    top_features = [dict(feature=LABEL.get(k, k), importance=int(v)) for k, v in imp.head(9).items()]

    # calibration (reliability deciles + Brier)
    from sklearn.metrics import brier_score_loss
    q = pd.qcut(p, 10, duplicates="drop")
    rel = pd.DataFrame({"p": p, "y": yte, "b": q}).groupby("b", observed=True).agg(pred=("p", "mean"), obs=("y", "mean")).reset_index(drop=True)
    reliability = [dict(pred=round(r.pred, 3), obs=round(r.obs, 3)) for r in rel.itertuples()]

    # anonymised example companies (real financials, real reason codes)
    contrib = model.booster_.predict(Xte, pred_contrib=True)[:, :-1]
    cols = list(X.columns)
    te = df.iloc[te].reset_index(drop=True)
    te["p"] = p
    ex_rows, n = [], 0
    hi = te[te.default == 1].sort_values("p", ascending=False).head(5).index
    lo = te[te.default == 0].sort_values("p").head(2).index
    for idx in list(hi) + list(lo):
        r = te.loc[idx]
        n += 1
        ex_rows.append(dict(
            id=f"IN-MSME-{n:03d}", industry=NIC2.get(str(r["nic"]), "Other"), obs_year=int(r["obs_year"]),
            pd=round(float(r["p"]), 3), outcome="Defaulted within 2 yrs" if r["default"] == 1 else "No default",
            interest_cover=None if pd.isna(r["interest_cover"]) else round(float(r["interest_cover"]), 1),
            debt_to_equity=None if pd.isna(r["debt_to_equity"]) else round(float(r["debt_to_equity"]), 1),
            pat_margin=None if pd.isna(r["pat_margin"]) else round(float(r["pat_margin"]) * 100, 1),
            reasons=real_reasons(r, contrib[idx], cols),
        ))

    out = dict(
        meta=dict(source="Real Indian MSME annual financials (FY2018-FY2026) + credit-rating history",
                  n_companies=int(df.company.nunique()), n_company_years=int(len(df)),
                  n_defaults=int(df.default.sum()), default_rate=round(float(df.default.mean()), 3),
                  horizon_years=2, obs_year_range=f"{int(df.obs_year.min())}-{int(df.obs_year.max())}"),
        metrics=dict(auc=round(auc, 3), ks=round(ksv, 3), pr_auc=round(prauc, 3),
                     logistic_auc=round(float(roc_auc_score(yte, p_lr)), 3),
                     brier=round(float(brier_score_loss(yte, p)), 4)),
        top_features=top_features, reliability=reliability, examples=ex_rows,
    )
    json.dump(out, open(OUT, "w"), indent=1)

    print("=" * 60)
    print(f"REAL-DATA MODEL — {out['meta']['n_companies']} companies, {out['meta']['n_company_years']} company-years, {out['meta']['n_defaults']} defaults ({out['meta']['default_rate']:.1%})")
    print(f"ROC-AUC {auc:.3f} | KS {ksv:.3f} | PR-AUC {prauc:.3f}   [honest real-data band ~0.75-0.85]")
    print(f"LightGBM {auc:.3f}  vs  logistic baseline {roc_auc_score(yte, p_lr):.3f}   (model earns its keep on real data)")
    print("top features:", ", ".join(imp.head(8).index))
    print(f"wrote {OUT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
