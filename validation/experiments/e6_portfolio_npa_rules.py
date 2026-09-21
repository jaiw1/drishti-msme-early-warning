"""E6 — one 90-DPD rule for eight portfolios, and what it costs to keep it.

Review section 11: "The generator also uses one 90-DPD definition across portfolios, including
KCC/agriculture... use portfolio-appropriate event labels and classification logic. Applicable
agricultural advances can have crop-season-linked NPA rules, while ordinary term-loan and CC/OD
rules differ. Have the bank confirm those policies before representing this as regulatory
classification."

RBI's IRAC norms do not apply the 90-day test to crop advances. A short-duration crop loan
becomes NPA when principal or interest has been overdue for **two crop seasons**, a
long-duration one after **one crop season**. The generator applied 90 DPD to all eight
portfolios including Kisan Credit Card, so every Agri label in the shipped panel is an event
the bank's own rules would have recognised roughly a year later.

`GeneratorConfig.portfolio_npa_rules` now switches on per-portfolio recognition
(`Portfolio.npa_recognition_months`; only `agri` is non-zero, at 12 months ≈ two kharif/rabi
seasons). **It is off by default and the shipped panel does not use it.** That is deliberate,
and it is the review's own instruction: a label definition is not a free parameter, changing it
moves every downstream number and several pre-registered bands, and the bank must confirm its
classification policy before any of this is represented as regulatory classification. This
experiment measures the size of the difference so the decision is informed rather than
inherited.

Three questions:

1. **How much does the label move?** Book and per-portfolio 12-month rates under both rules.
2. **Does the SHIPPED model still rank the re-labelled book?** The frozen artefact scores it
   with no refit — which is exactly what would happen on day one if the bank corrected its
   label definition without retraining.
3. **What would a model fitted under the correct rule look like?** One refit, same
   hyperparameters, so the gap between "inherit" and "retrain" is visible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from validation.experiments import artefact as A

OUT = A.REPO_ROOT / "validation" / "report" / "experiments" / "portfolio_npa_rules"
ACCOUNTS = 9_000
MONTHS = 36
SEED = 20260709


def _ensure_src():
    src = str(A.REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _rates(panel: pd.DataFrame) -> dict:
    _ensure_src()
    import export_demo as ed

    elig = panel[ed.eligible_rows(panel)]
    per = {
        str(code): dict(
            n_rows=int(len(g)),
            rate_12m=round(float(g["default_within_12m"].mean()), 5),
            median_months_to_npa=(
                None if not (g["months_to_npa"] >= 1).any()
                else float(g.loc[g["months_to_npa"] >= 1, "months_to_npa"].median())),
        )
        for code, g in elig.groupby(elig["portfolio"].astype(str))
    }
    return dict(book_rate_12m=round(float(elig["default_within_12m"].mean()), 5),
                n_eligible_rows=int(len(elig)), by_portfolio=per)


def _score_frozen(panel: pd.DataFrame, art: A.Artefact) -> dict:
    """The SHIPPED model on this book, no refit — the 'bank corrects the label and
    keeps the model' case."""
    _ensure_src()
    import export_demo as ed
    from sklearn.metrics import roc_auc_score

    elig = panel[ed.eligible_rows(panel)].reset_index(drop=True)
    decision = art.decision_score(elig)
    y = elig["default_within_12m"].to_numpy()
    out = dict(auc_overall=round(float(roc_auc_score(y, decision)), 4)
               if len(np.unique(y)) > 1 else None)
    per = {}
    for code, idx in elig.groupby(elig["portfolio"].astype(str)).groups.items():
        pos = elig.index.get_indexer(idx)
        yy, dd = y[pos], decision[pos]
        per[str(code)] = (round(float(roc_auc_score(yy, dd)), 4)
                          if len(np.unique(yy)) > 1 else None)
    out["auc_by_portfolio"] = per
    return out


def _refit(panel: pd.DataFrame) -> dict:
    """One fit under the new rule, same hyperparameters — the 'retrain' case."""
    _ensure_src()
    import export_demo as ed
    from lightgbm import LGBMClassifier
    from sklearn.metrics import roc_auc_score

    df = panel.copy()
    ed.add_elapsed_time_bands(df)
    cats = [c for c in ed.CAT if c in df.columns]
    for c in cats:
        df[c] = df[c].astype("category")
    y = df["default_within_12m"].to_numpy()
    X = df.drop(columns=[c for c in ed.DROP if c in df.columns])
    labelable = ed.eligible_rows(df)
    fit, _pol, te = ed.three_way_split(df["account_id"].to_numpy())
    fit_lab, te_lab = fit[labelable[fit]], te[labelable[te]]
    m = LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
                       colsample_bytree=0.8, min_child_samples=80, random_state=7,
                       n_jobs=-1, verbose=-1)
    m.fit(X.iloc[fit_lab], y[fit_lab], categorical_feature=cats)
    p = m.predict_proba(X.iloc[te_lab])[:, 1]
    yy = y[te_lab]
    per = {}
    sub = df.iloc[te_lab].reset_index(drop=True)
    for code, idx in sub.groupby(sub["portfolio"].astype(str)).groups.items():
        pos = sub.index.get_indexer(idx)
        per[str(code)] = (round(float(roc_auc_score(yy[pos], p[pos])), 4)
                          if len(np.unique(yy[pos])) > 1 else None)
    return dict(auc_overall=round(float(roc_auc_score(yy, p)), 4), auc_by_portfolio=per,
                n_train_rows=int(len(fit_lab)), n_test_rows=int(len(te_lab)))


def run() -> dict:
    _ensure_src()
    from generator import GeneratorConfig, generate
    from generator.portfolios import NPA_RECOGNITION_MONTHS

    art = A.load()
    books = {}
    for name, flag in (("dpd90_everywhere", False), ("portfolio_appropriate", True)):
        panel, _ = generate(GeneratorConfig(seed=SEED, n_accounts=ACCOUNTS, months=MONTHS,
                                            portfolio_npa_rules=flag))
        panel = panel.assign(account_id=panel["account_id"].astype(str))
        books[name] = dict(rule=name, portfolio_npa_rules=flag, **_rates(panel))
        books[name]["frozen_model"] = _score_frozen(panel, art)
        books[name]["refit"] = _refit(panel)
        print(f"  {name:<22s} book {books[name]['book_rate_12m']:.4f}  "
              f"Agri {books[name]['by_portfolio'].get('Agri', {}).get('rate_12m')}  "
              f"frozen AUC {books[name]['frozen_model']['auc_overall']}  "
              f"refit AUC {books[name]['refit']['auc_overall']}")

    result = dict(
        experiment="portfolio_npa_rules",
        question=("What does applying one 90-DPD rule to all eight portfolios — including "
                  "Kisan Credit Card — cost, compared with RBI's crop-season rule for "
                  "agricultural advances?"),
        rule=dict(
            default="90 DPD for every portfolio (what the shipped panel uses)",
            alternative=("Portfolio.npa_recognition_months: +12 months for agri (two "
                         "kharif/rabi crop seasons), 0 elsewhere"),
            recognition_months=dict(NPA_RECOGNITION_MONTHS),
            citation=("RBI Master Circular on Income Recognition, Asset Classification and "
                      "Provisioning: a short-duration crop advance is NPA when principal or "
                      "interest is overdue for two crop seasons; a long-duration crop advance "
                      "for one crop season. Ordinary term loans use 90 days overdue; CC/OD "
                      "uses 'out of order' for more than 90 days."),
            shipped_default=("OFF. The shipped panel keeps 90 DPD everywhere. A label "
                             "definition is not a free parameter, and the review's own "
                             "instruction is to have the bank confirm its classification "
                             "policy before this is represented as regulatory classification."),
        ),
        panel=dict(seed=SEED, n_accounts=ACCOUNTS, months=MONTHS),
        artefact=art.manifest,
        books=books,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=1))
    _write_markdown(result)
    return result


def _write_markdown(r: dict) -> None:
    a, b = r["books"]["dpd90_everywhere"], r["books"]["portfolio_appropriate"]
    codes = sorted(set(a["by_portfolio"]) | set(b["by_portfolio"]))
    L = ["# E6 — one 90-DPD rule for eight portfolios, and what it costs", "",
         f"**Question.** {r['question']}", "",
         f"**The rule.** {r['rule']['citation']}", "",
         f"**Default: {r['rule']['shipped_default']}**", "",
         f"Panel {r['panel']['n_accounts']:,} accounts × {r['panel']['months']} months, "
         f"seed {r['panel']['seed']} — the same seed on both sides, so the only difference "
         f"is the recognition rule.", "",
         "## 1. How much does the label move?", "",
         "| portfolio | 12m rate, 90 DPD | 12m rate, portfolio rule | change |",
         "|---|---|---|---|"]
    for code in codes:
        ra = a["by_portfolio"].get(code, {}).get("rate_12m")
        rb = b["by_portfolio"].get(code, {}).get("rate_12m")
        delta = "—" if ra is None or rb is None else f"{(rb - ra) / ra:+.0%}"
        L.append(f"| {code} | {ra if ra is None else f'{ra:.2%}'} "
                 f"| {rb if rb is None else f'{rb:.2%}'} | {delta} |")
    L += [f"| **book** | **{a['book_rate_12m']:.2%}** | **{b['book_rate_12m']:.2%}** | "
          f"**{(b['book_rate_12m'] - a['book_rate_12m']) / a['book_rate_12m']:+.0%}** |", "",
          "Only agriculture changes, which is the point: every other portfolio here is an "
          "ordinary term loan or a CC/OD facility, and 90 days is the right test for both. "
          "Agri's rate falls because a crop advance that the 90-day rule calls NPA is, under "
          "the bank's actual norms, still a standard asset for roughly another year — and "
          "some of those accounts never reach the corrected recognition point inside the "
          "observation window at all.", "",
          "## 2. Does the SHIPPED model still rank the re-labelled book?", "",
          "The frozen artefact scoring each book with **no refit** — the day-one case if a "
          "bank corrects its label definition and keeps the model it already has.", "",
          "| portfolio | frozen AUC, 90 DPD | frozen AUC, portfolio rule |",
          "|---|---|---|"]
    for code in codes:
        fa = a["frozen_model"]["auc_by_portfolio"].get(code)
        fb = b["frozen_model"]["auc_by_portfolio"].get(code)
        L.append(f"| {code} | {fa} | {fb} |")
    L += [f"| **overall** | **{a['frozen_model']['auc_overall']}** | "
          f"**{b['frozen_model']['auc_overall']}** |", "",
          "## 3. What would retraining under the correct rule buy?", "",
          "| | 90 DPD | portfolio rule |", "|---|---|---|",
          f"| frozen model (no refit) | {a['frozen_model']['auc_overall']} | "
          f"{b['frozen_model']['auc_overall']} |",
          f"| refit under that rule | {a['refit']['auc_overall']} | "
          f"{b['refit']['auc_overall']} |",
          f"| Agri, frozen | {a['frozen_model']['auc_by_portfolio'].get('Agri')} | "
          f"{b['frozen_model']['auc_by_portfolio'].get('Agri')} |",
          f"| Agri, refit | {a['refit']['auc_by_portfolio'].get('Agri')} | "
          f"{b['refit']['auc_by_portfolio'].get('Agri')} |", "",
          "## What this does and does not settle", "",
          "It settles that the single 90-DPD definition materially mis-states agriculture, and "
          "by roughly how much. It does **not** settle what IDBI's own classification policy "
          "is — short- versus long-duration crop mix, how a KCC renewal interacts with "
          "recognition, and whether the bank treats the seasons as half-years. Those are the "
          "bank's to confirm, which is why the switch ships off. Nothing in DRISHTi assigns a "
          "regulatory classification in either configuration: the memo recommends a credit "
          "review and reports the CBS classification as an observed field.", ""]
    (OUT / "REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    print("E6 — portfolio-appropriate NPA recognition:")
    run()
    print(f"E6 -> {OUT}")
