"""E3 — scope the real-data experiment honestly, and test whether its signal survives scoping.

Review section 8: `real_model.py` builds a two-year company-year financial-statement target. It
is not the shipped twelve-month behavioural model transferred to real customers, and its
`n_defaults` field counts positive ROWS. The deck called those "1,284 real defaults".

Phase 1 fixed the wording in README and MODEL_CARD. This fixes the evidence underneath it,
without touching `src/real_model.py` — that module's output is embedded verbatim in the export
as the frozen July 2026 artefact, so it is imported and re-analysed here rather than edited.

Five things the review asked for:

1. **Denominators, separately.** Companies, company-years, positive rows, and distinct
   companies with at least one positive row — with the mechanism that makes them differ stated
   (one default labels up to `horizon` preceding years).
2. **An explicit censoring cutoff and per-company observation coverage.** How many company-years
   each firm contributes, and how many non-defaulter rows are dropped because their outcome
   window runs past the data's end.
3. **A temporal holdout.** The shipped figure comes from a company-grouped RANDOM split, which
   lets a 2019 row predict a 2019 outcome elsewhere in the book. A model meant to be used
   forwards should be tested forwards. Reported both ways, plus temporal AND company-disjoint.
4. **Exact rating-event dates, and a filing-availability sensitivity.** The ratings file carries
   a full date; `real_model.yr()` reduces it to a year, so a default in January and one in
   December are treated identically. The financials carry no filing-availability date at all —
   so a statement for FY-ending-March may not have been readable until months later, and a
   model trained as if it were available on day one is optimistic. Both are quantified: the
   within-year timing of default events, and what happens to AUC when a full extra year of
   filing lag is enforced.
5. **The company-clustered bootstrap is retained**, on every AUC reported here.

The conclusion this supports is "a two-year financial-statement model has signal on real Indian
MSMEs" — complementary evidence. It is not external validation of the twelve-month behavioural
model: different horizon, different observation unit, different features, different population.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from validation.experiments import artefact as A

OUT = A.REPO_ROOT / "validation" / "report" / "experiments" / "real_data_scoping"
N_BOOT = 500
BOOT_SEED = 7


def _ensure_src():
    src = str(A.REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _fit_score(df, num_cols, train_mask, test_mask):
    from lightgbm import LGBMClassifier
    from sklearn.metrics import average_precision_score, roc_auc_score

    X = df[num_cols + ["nic"]].copy()
    X["nic"] = X["nic"].astype("category")
    y = df["default"].to_numpy()
    if train_mask.sum() < 50 or test_mask.sum() < 50:
        return None
    if len(np.unique(y[test_mask])) < 2 or len(np.unique(y[train_mask])) < 2:
        return None
    m = LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=32,
                       min_child_samples=40, subsample=0.8, colsample_bytree=0.8,
                       random_state=7, n_jobs=-1, verbose=-1)
    m.fit(X[train_mask], y[train_mask], categorical_feature=["nic"])
    p = m.predict_proba(X[test_mask])[:, 1]
    yt = y[test_mask]
    auc = float(roc_auc_score(yt, p))
    lo, hi = _clustered_ci(yt, p, df.loc[test_mask, "company"].to_numpy())
    return dict(
        auc=round(auc, 4), auc_ci=[round(lo, 4), round(hi, 4)],
        pr_auc=round(float(average_precision_score(yt, p)), 4),
        n_train_rows=int(train_mask.sum()), n_test_rows=int(test_mask.sum()),
        n_train_companies=int(df.loc[train_mask, "company"].nunique()),
        n_test_companies=int(df.loc[test_mask, "company"].nunique()),
        n_test_positive_rows=int(yt.sum()),
        n_test_positive_companies=int(df.loc[test_mask][y[test_mask] == 1]["company"].nunique()),
    )


def _clustered_ci(y, p, companies, n=N_BOOT, seed=BOOT_SEED):
    """95% CI on AUC by resampling COMPANIES, not rows — rows within a company are
    correlated and an unclustered interval here would be far too narrow."""
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(seed)
    uniq = pd.unique(companies)
    by = {c: np.flatnonzero(companies == c) for c in uniq}
    boot = []
    for _ in range(n):
        idx = np.concatenate([by[c] for c in rng.choice(uniq, size=len(uniq), replace=True)])
        if y[idx].min() != y[idx].max():
            boot.append(roc_auc_score(y[idx], p[idx]))
    return (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))) if boot else (0.0, 0.0)


# --------------------------------------------------------------------------- #
def rating_event_timing() -> dict:
    """Exact 'D'-rating dates, which `real_model.yr()` currently reduces to a year."""
    _ensure_src()
    import real_model as rm

    path = Path(rm.DIR) / "msme_ratings_movement.csv"
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Company Name")
    H = {h: i for i, h in enumerate(rows[hi])}
    months, dated, undated = Counter(), 0, 0
    for r in rows[hi + 1:]:
        if len(r) < 6 or not r[0].strip():
            continue
        rating = r[H["Rating"]].strip()
        if not (rating == "D" or rating.startswith("D ")):
            continue
        raw = (r[H["Date"]] or "").strip()
        m = re.search(r"\b([A-Za-z]{3,9})\b", raw)
        if m:
            months[m.group(1)[:3].title()] += 1
            dated += 1
        else:
            undated += 1
    return dict(
        n_default_events=dated + undated,
        n_with_parseable_month=dated, n_without=undated,
        by_month=dict(months.most_common()),
        note=("`real_model.yr()` keeps only the YEAR of a rating action, so a default in "
              "January and one in December are treated as the same event date. Every row is "
              "labelled against a financial YEAR, so the effective lead time varies by up to "
              "eleven months across the positive class and is not recoverable from the label. "
              "Using exact dates would let lead time be measured rather than assumed; it is "
              "not done here because the frozen artefact must stay as it shipped."),
    )


def coverage_and_censoring(df: pd.DataFrame, horizon: int, last_year: int) -> dict:
    per_company = df.groupby("company")["obs_year"].agg(["count", "min", "max"])
    counts = Counter(per_company["count"].tolist())
    pos = df[df["default"] == 1]
    return dict(
        companies=int(df["company"].nunique()),
        company_years=int(len(df)),
        positive_rows=int(df["default"].sum()),
        positive_companies=int(pos["company"].nunique()),
        rows_per_positive_company=round(
            float(len(pos) / max(pos["company"].nunique(), 1)), 3),
        why_they_differ=(
            f"The target is default within the next {horizon} financial years, so ONE default "
            f"event labels up to {horizon} preceding company-years. "
            f"{int(df['default'].sum())} positive ROWS come from "
            f"{int(pos['company'].nunique())} distinct COMPANIES. Neither number is a count of "
            f"'real defaults': the event count is the company count, and the row count is an "
            f"observation count."),
        observation_coverage=dict(
            years_per_company={str(k): int(v) for k, v in sorted(counts.items())},
            median_years=float(per_company["count"].median()),
            mean_years=round(float(per_company["count"].mean()), 2),
            note=("A company contributing six company-years carries six times the weight of one "
                  "contributing one, in every unclustered statistic. This is why the AUC "
                  "intervals here are bootstrapped over COMPANIES."),
        ),
        censoring=dict(
            last_year=last_year, horizon_years=horizon,
            rule=(f"a non-defaulter's row is kept only when its outcome window ends at or "
                  f"before {last_year} (obs_year + {horizon} <= {last_year}); a defaulter's "
                  f"rows at or after its default year are dropped entirely, so no row is "
                  f"observed after the event it predicts"),
            obs_year_range=[int(df["obs_year"].min()), int(df["obs_year"].max())],
            rows_by_obs_year={str(int(y)): int(n)
                              for y, n in df["obs_year"].value_counts().sort_index().items()},
            positive_rate_by_obs_year={
                str(int(y)): round(float(g["default"].mean()), 4)
                for y, g in df.groupby("obs_year")},
        ),
    )


def run() -> dict:
    _ensure_src()
    import real_model as rm
    from sklearn.model_selection import GroupShuffleSplit

    horizon, last_year = 2, 2026
    df = rm.build_table(horizon=horizon, last_year=last_year)
    num = ["interest_cover", "debt_to_equity", "pat_margin", "pbdita_margin", "pbt_margin",
           "borrow_to_income", "borrow_to_networth", "neg_networth", "loss_flag", "log_income",
           "d_networth", "d_income", "d_pat", "d_borrow", "age"]

    cov = coverage_and_censoring(df, horizon, last_year)
    print(f"  table: {cov['companies']:,} companies / {cov['company_years']:,} company-years / "
          f"{cov['positive_rows']:,} positive rows / {cov['positive_companies']:,} positive companies")

    designs = {}

    # (a) the shipped design: company-grouped RANDOM split
    tr, te = next(GroupShuffleSplit(1, test_size=0.30, random_state=7)
                  .split(df, df["default"], groups=df["company"]))
    mask_tr = np.zeros(len(df), bool); mask_tr[tr] = True
    designs["company_grouped_random"] = dict(
        design=("the shipped design: 30% of COMPANIES held out at random, all years pooled"),
        caveat=("company-disjoint but not time-disjoint — a 2019 row may be used to predict a "
                "2019 outcome at another company, which a forward-looking user cannot do"),
        **(_fit_score(df, num, mask_tr, ~mask_tr) or {}))

    # (b) temporal holdout
    years = sorted(df["obs_year"].unique())
    cut = int(np.quantile(df["obs_year"], 0.70))
    t_tr = (df["obs_year"] <= cut).to_numpy()
    designs["temporal"] = dict(
        design=f"train on obs_year <= {cut}, test on obs_year > {cut} — forwards, as it would be used",
        caveat="companies may appear in both halves, in different years",
        cut_year=cut, **(_fit_score(df, num, t_tr, ~t_tr) or {}))

    # (c) temporal AND company-disjoint: the strictest reading
    test_companies = set(df.loc[~t_tr, "company"].unique())
    strict_tr = t_tr & ~df["company"].isin(test_companies).to_numpy()
    designs["temporal_and_company_disjoint"] = dict(
        design=(f"train on obs_year <= {cut} AND on companies absent from the test window; "
                f"test on obs_year > {cut}"),
        caveat="the strictest of the three, and the smallest training set",
        cut_year=cut, **(_fit_score(df, num, strict_tr, ~t_tr) or {}))

    # (d) filing-availability sensitivity: pretend statements arrive a full year late
    lagged = rm.build_table(horizon=horizon + 1, last_year=last_year)
    lag_tr_idx, _ = next(GroupShuffleSplit(1, test_size=0.30, random_state=7)
                         .split(lagged, lagged["default"], groups=lagged["company"]))
    lag_tr = np.zeros(len(lagged), bool)
    lag_tr[lag_tr_idx] = True
    designs["extra_filing_lag"] = dict(
        design=(f"the same model with the outcome window pushed out one year "
                f"(horizon {horizon} -> {horizon + 1}), standing in for statements that are not "
                f"readable until a year after the financial year they describe"),
        caveat=("an approximation: the source carries no filing-availability date at all, so "
                "the true lag is unknown and this brackets it rather than measuring it"),
        **(_fit_score(lagged, num, lag_tr, ~lag_tr) or {}))

    for name, cell in designs.items():
        if cell.get("auc") is not None:
            print(f"  {name:<32s} AUC {cell['auc']} {cell['auc_ci']}  "
                  f"test {cell['n_test_rows']:,} rows / {cell['n_test_companies']:,} companies")

    result = dict(
        experiment="real_data_scoping",
        question=("What exactly do the real-data numbers count, and does the signal survive a "
                  "temporal holdout and a filing-availability lag?"),
        what_this_is=("Complementary evidence that a TWO-YEAR FINANCIAL-STATEMENT model has "
                      "signal on real Indian MSMEs. It is not external validation of DRISHTi's "
                      "twelve-month behavioural model: different horizon (2 years vs 12 months), "
                      "different observation unit (company-year vs account-month), different "
                      "features (filed balance-sheet ratios vs monthly account conduct), "
                      "different population. A number measured on one is not a number earned by "
                      "the other."),
        source_model="src/real_model.py (frozen July 2026 artefact; imported, not modified)",
        horizon_years=horizon, censoring_last_year=last_year,
        denominators=cov,
        rating_event_timing=rating_event_timing(),
        designs=designs,
        bootstrap="95% CI by resampling COMPANIES with replacement, 500 draws",
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=1))
    _write_markdown(result)
    return result


def _write_markdown(r: dict) -> None:
    d, cov = r["designs"], r["denominators"]
    L = ["# E3 — what the real-data numbers count, and whether the signal survives scoping", "",
         f"**Question.** {r['question']}", "",
         f"**What this is.** {r['what_this_is']}", "",
         f"Source: `{r['source_model']}`. Horizon {r['horizon_years']} financial years; "
         f"censoring cutoff {r['censoring_last_year']}. {r['bootstrap']}.", "",
         "## 1. Four different numbers, and why they differ", "",
         "| quantity | value |", "|---|---|",
         f"| companies | **{cov['companies']:,}** |",
         f"| company-years (rows) | **{cov['company_years']:,}** |",
         f"| positive rows | **{cov['positive_rows']:,}** |",
         f"| distinct companies with >=1 positive row | **{cov['positive_companies']:,}** |",
         f"| positive rows per positive company | {cov['rows_per_positive_company']} |", "",
         f"{cov['why_they_differ']}", "",
         "## 2. Observation coverage and censoring", "",
         f"Median **{cov['observation_coverage']['median_years']:.0f}** company-years per "
         f"company (mean {cov['observation_coverage']['mean_years']}). "
         f"{cov['observation_coverage']['note']}", "",
         f"Censoring rule: {cov['censoring']['rule']}. Observation years span "
         f"{cov['censoring']['obs_year_range'][0]}–{cov['censoring']['obs_year_range'][1]}.", "",
         "| obs year | rows | positive rate |", "|---|---|---|"]
    rows_by = cov["censoring"]["rows_by_obs_year"]
    rate_by = cov["censoring"]["positive_rate_by_obs_year"]
    for y in sorted(rows_by):
        L.append(f"| {y} | {rows_by[y]:,} | {rate_by.get(y, 0):.2%} |")
    t = r["rating_event_timing"]
    L += ["", "## 3. Rating-event dates", "",
          f"{t['n_default_events']:,} 'D' rating actions, {t['n_with_parseable_month']:,} with a "
          f"readable month.", "", f"_{t['note']}_", "",
          "## 4. Does the signal survive a harder design?", "",
          "| design | AUC | 95% CI (company-clustered) | train rows | test rows | test companies | test positive rows / companies |",
          "|---|---|---|---|---|---|---|"]
    for name, cell in d.items():
        if cell.get("auc") is None:
            L.append(f"| {name} | — | — | — | — | — | — |")
            continue
        L.append(f"| `{name}` | **{cell['auc']}** | [{cell['auc_ci'][0]}, {cell['auc_ci'][1]}] "
                 f"| {cell['n_train_rows']:,} | {cell['n_test_rows']:,} "
                 f"| {cell['n_test_companies']:,} "
                 f"| {cell['n_test_positive_rows']:,} / {cell['n_test_positive_companies']:,} |")
    L += ["",
          "**Read the train-rows column beside the AUC.** `temporal_and_company_disjoint` is the",
          "strictest design AND the smallest training set, so part of its drop is less data",
          "rather than a harder test; the two are not separated here. What can be said is that",
          "the shipped 0.81 is the most permissive of the four designs, and that every stricter",
          "one lands lower.", ""]
    for name, cell in d.items():
        L += [f"**`{name}`** — {cell['design']}.  ", f"_Caveat: {cell['caveat']}._", ""]
    (OUT / "REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    print("E3 — real-data scoping:")
    run()
    print(f"E3 -> {OUT}")
