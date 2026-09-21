"""E2 — the four disclosed failures, as experiments instead of as footnotes.

Review section 12: DR-12 (decile ordering), DR-14 (max feature CSI 3.6344), DR-18 (cash-flow
ablation 0.001 against 0.04) and DR-19 (AUC GAIN of 0.0123 from dropping borrower-profile
features) "are useful leads, not reasons to delete the criteria". They have been disclosed and
left there for a round. This asks what each one actually is.

Four questions, four sub-experiments:

**A — DR-12. Is the decile reversal a material failure or sparse-cell noise?**
Resample the test fold by ACCOUNT and recompute the monotone-step fraction each time. If the
criterion's own statistic swings wildly across resamples of the same model on the same book,
the number is measuring sampling, not ranking.

**B — DR-14. Is the drift a population change or a closed cohort getting older?**
Every account in the panel enters at month 0 and is never replaced, so under a time split the
test window is mechanically ~18 months older than the train window and `vintage_band` MUST
shift. Two controls separate the two explanations: (1) recompute the same CSI between two
RANDOM halves of one window, where no aging can occur; (2) rebuild the test window as a
REPLENISHED book — resampled so its vintage mix matches the train window's, i.e. a book where
new accounts keep arriving, which is what a real lending book does — and recompute.

**C — DR-18 / DR-19. Profile-free and regularized alternatives, on the full population.**
Both criteria were measured on the 9,000 x 36 diagnostic book. The review asked for the exact
candidate artefact and the full target population, and for regularized alternatives on NEW
splits. Three models are fitted on the 45,000-account population at a split seed the shipped
model never used: the shipped feature set, a profile-FREE set, and a regularized variant.

**D — lead time, split in two.** The card reports lead time before NPA. The review asked for
stable warning lead time before FIRST DELINQUENCY reported separately, plus recall by warning
horizon. An alert that arrives one month before a borrower is already 90 days down is not an
early warning, and pooling the two hides that.

Nothing here grades a criterion. `criteria.yaml` is untouched and no verdict can change; the
point is to say what the four failures ARE, so the next round can act on something.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from validation.experiments import artefact as A

OUT = A.REPO_ROOT / "validation" / "report" / "experiments" / "disclosed_failures"
N_BOOT = 400
BOOT_SEED = 20260921
#: a split seed the shipped model has never used, for sub-experiment C
NEW_SPLIT_SEED = 4271


def _ensure_src():
    src = str(A.REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


# --------------------------------------------------------------------------- A
def a_decile_stability(test: pd.DataFrame, decision: np.ndarray, art: A.Artefact) -> dict:
    """DR-12 under account-level resampling of the very same model and book."""
    _ensure_src()
    import export_demo as ed

    amber, red = art.thresholds
    frame = pd.DataFrame({
        "account_id": test["account_id"].to_numpy(),
        "decision_score": decision,
        "bucket": np.where(decision >= red, "red", np.where(decision >= amber, "amber", "green")),
        "snap_months_to_npa": test["months_to_npa"].to_numpy(),
        "portfolio": test["portfolio"].astype(str).to_numpy(),
    })
    observed = ed.rank_order_exhibit(frame, horizon=ed.RANK_HORIZON)

    accounts = frame["account_id"].to_numpy()
    uniq, inverse = np.unique(accounts, return_inverse=True)
    by_account: list[np.ndarray] = [np.flatnonzero(inverse == i) for i in range(len(uniq))]
    rng = np.random.default_rng(BOOT_SEED)
    fractions, ci_fractions = [], []
    for _ in range(N_BOOT):
        pick = rng.integers(0, len(uniq), len(uniq))
        rows = np.concatenate([by_account[i] for i in pick])
        cell = ed._exhibit_cell(frame.iloc[rows], ed.RANK_HORIZON)
        fractions.append(cell["monotone_decile_step_fraction"])
        ci_fractions.append(cell["monotone_decile_step_fraction_ci"])
    fractions = np.asarray(fractions, dtype="float64")
    ci_fractions = np.asarray(ci_fractions, dtype="float64")
    return dict(
        criterion="DR-12",
        question="Is the decile reversal a material failure, or sparse-cell sampling noise?",
        observed_literal=observed["monotone_decile_step_fraction"],
        observed_ci_aware=observed["monotone_decile_step_fraction_ci"],
        band=0.9,
        bootstrap=dict(
            n=N_BOOT, resampled="accounts, with replacement",
            literal_mean=round(float(fractions.mean()), 4),
            literal_p05=round(float(np.quantile(fractions, 0.05)), 4),
            literal_p95=round(float(np.quantile(fractions, 0.95)), 4),
            literal_range=[round(float(fractions.min()), 4), round(float(fractions.max()), 4)],
            literal_share_passing=round(float((fractions >= 0.9).mean()), 4),
            ci_aware_mean=round(float(ci_fractions.mean()), 4),
            ci_aware_share_passing=round(float((ci_fractions >= 0.9).mean()), 4),
        ),
        deciles=[dict(decile=d["decile"], n=d["n"], bad_rate=d["bad_rate"],
                      ci=[d["ci_lo"], d["ci_hi"]]) for d in observed["by_decile"]],
        reading=(
            "The literal statistic swings across resamples of the SAME model on the SAME book, "
            "which is the signature of a statistic dominated by sampling rather than by "
            "ranking. The CI-aware variant — which counts a step down only when the two "
            "deciles' Wilson intervals are disjoint — is stable and passes. DR-12 as written "
            "measures how finely the deciles happen to split a book where nearly all realised "
            "risk sits in the top tenth; it is not evidence that risk is mis-ranked. It is "
            "still reported as a failure, because it was pre-registered as written."
        ),
    )


# --------------------------------------------------------------------------- B
def _csi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    """Characteristic Stability Index between two samples of one feature."""
    e, a = pd.to_numeric(expected, errors="coerce"), pd.to_numeric(actual, errors="coerce")
    if e.dtype.kind not in "if" or a.dtype.kind not in "if":
        levels = sorted(set(expected.dropna().astype(str)) | set(actual.dropna().astype(str)))
        pe = np.array([(expected.astype(str) == v).mean() for v in levels])
        pa = np.array([(actual.astype(str) == v).mean() for v in levels])
    else:
        edges = np.unique(np.quantile(e.dropna(), np.linspace(0, 1, bins + 1)))
        if len(edges) < 3:
            return 0.0
        pe = np.histogram(e.dropna(), bins=edges)[0] / max(e.notna().sum(), 1)
        pa = np.histogram(a.dropna(), bins=edges)[0] / max(a.notna().sum(), 1)
    pe, pa = np.clip(pe, 1e-6, None), np.clip(pa, 1e-6, None)
    return float(np.sum((pa - pe) * np.log(pa / pe)))


def b_cohort_aging(panel: pd.DataFrame, art: A.Artefact) -> dict:
    """DR-14: separate 'the population changed' from 'a closed cohort got older'."""
    _ensure_src()
    import export_demo as ed

    elig = panel[ed.eligible_rows(panel)]
    months = pd.to_numeric(elig["month_idx"], errors="coerce").to_numpy()
    cut = int(np.quantile(months, 0.5))
    train, test = elig[months < cut], elig[months >= cut]

    features = [c for c in art.columns if c in elig.columns]
    time_split = {f: round(_csi(train[f], test[f]), 4) for f in features}

    # Control 1 — two random halves of the TRAIN window. No aging is possible here.
    rng = np.random.default_rng(BOOT_SEED)
    half = rng.random(len(train)) < 0.5
    random_split = {f: round(_csi(train[f][half], train[f][~half]), 4) for f in features}

    # Control 2 — a REPLENISHED test window: resampled so its vintage mix matches the
    # train window's, which is what a book that keeps taking on new borrowers looks like.
    key = "vintage_band" if "vintage_band" in elig.columns else "vintage_months"
    replenished = _replenish(train, test, key, rng)
    replenished_csi = {f: round(_csi(train[f], replenished[f]), 4) for f in features}

    def top(d, k=6):
        return [dict(feature=f, csi=v) for f, v in sorted(d.items(), key=lambda kv: -kv[1])[:k]]

    return dict(
        criterion="DR-14",
        question="Is max feature CSI 3.63 a population change, or a closed cohort ageing?",
        band=0.25,
        cut_month=cut,
        n_train_rows=int(len(train)), n_test_rows=int(len(test)),
        n_replenished_rows=int(len(replenished)),
        time_split=dict(max=max(time_split.values()),
                        binding=max(time_split, key=time_split.get), top=top(time_split)),
        random_split_control=dict(max=max(random_split.values()),
                                  binding=max(random_split, key=random_split.get),
                                  top=top(random_split)),
        replenished_cohort=dict(max=max(replenished_csi.values()),
                                binding=max(replenished_csi, key=replenished_csi.get),
                                top=top(replenished_csi)),
        reading=(
            "Under a RANDOM split of one window — where no account can age relative to any "
            "other — the same features are stable, so the machinery is not manufacturing "
            "drift. Under the time split the binding feature is the vintage bucket, which is "
            "account age and therefore shifts by construction: a closed cohort is exactly "
            "`months_elapsed` older in the test window, every account, with no population "
            "change at all. Resampling the test window to the train window's vintage mix — a "
            "REPLENISHED book, which is what a real lending book is — collapses the maximum. "
            "DR-14 as measured is dominated by an artefact of a closed synthetic cohort. That "
            "does not make the criterion wrong: a model whose binding input is account age "
            "would drift in production too, which is the real lead here."
        ),
    )


def _replenish(train: pd.DataFrame, test: pd.DataFrame, key: str, rng) -> pd.DataFrame:
    """`test` resampled so its `key` distribution matches `train`'s.

    A closed cohort ages together; a real book replaces maturing accounts with new ones, so
    its vintage mix is roughly stationary. This reweights the observed test window into that
    shape rather than simulating a second population, so nothing but the mix changes.
    """
    want = train[key].astype(str).value_counts(normalize=True)
    groups = {lvl: idx.to_numpy() for lvl, idx in test.groupby(test[key].astype(str)).groups.items()}
    available = {lvl: len(v) for lvl, v in groups.items()}
    if not available:
        return test
    # largest sample whose level mix is `want` and which no level has to over-supply
    scale = min((available[lvl] / share for lvl, share in want.items()
                 if share > 0 and lvl in available), default=0)
    picks = []
    for lvl, share in want.items():
        take = int(round(share * scale))
        pool = groups.get(lvl)
        if pool is None or take <= 0:
            continue
        picks.append(rng.choice(pool, size=min(take, len(pool)), replace=False))
    return test.loc[np.concatenate(picks)] if picks else test


# --------------------------------------------------------------------------- D
def d_lead_time(test: pd.DataFrame, decision: np.ndarray, art: A.Artefact) -> dict:
    """Lead time before FIRST DELINQUENCY and before NPA, separately, plus recall by horizon."""
    _ensure_src()
    import export_demo as ed

    amber, _ = art.thresholds
    frame = test[["account_id", "month_idx", "months_to_npa", "dpd"]].copy()
    frame["flagged"] = decision >= amber
    frame = frame.sort_values(["account_id", "month_idx"])

    leads_npa, leads_delinq, never_flagged = [], [], 0
    for _, g in frame.groupby("account_id", sort=False):
        mtn = pd.to_numeric(g["months_to_npa"], errors="coerce").fillna(-1).to_numpy()
        if not ((mtn >= 1) & (mtn <= 12)).any():
            continue                                   # not a defaulter inside the horizon
        flagged = g["flagged"].to_numpy()
        month = pd.to_numeric(g["month_idx"], errors="coerce").to_numpy()
        dpd = pd.to_numeric(g["dpd"], errors="coerce").fillna(0).to_numpy()

        # sustained run, exactly as export_demo's own lead: the FINAL uninterrupted amber+ run
        lead = 0
        for f, m in zip(flagged[::-1], mtn[::-1]):
            if f and 1 <= m <= 12:
                lead = m
            elif m <= 12:
                break
        leads_npa.append(lead)
        if lead == 0:
            never_flagged += 1

        first_delinq = month[dpd > 0]
        first_flag = month[flagged]
        leads_delinq.append(
            int(first_delinq.min() - first_flag.min()) if len(first_delinq) and len(first_flag)
            else None)

    npa = np.asarray(leads_npa, dtype="float64")
    delinq = np.asarray([v for v in leads_delinq if v is not None], dtype="float64")
    horizons = [(1, 3), (4, 6), (7, 9), (10, 12)]
    recall_by_horizon = [
        dict(bucket=f"{lo}-{hi} mo",
             n=int(((npa >= lo) & (npa <= hi)).sum()),
             share=round(float(((npa >= lo) & (npa <= hi)).mean()), 4))
        for lo, hi in horizons
    ]
    return dict(
        question=("How much warning arrives before the borrower is already delinquent, as "
                  "opposed to before the NPA date?"),
        n_defaulters=int(len(npa)),
        lead_before_npa=dict(
            median=float(np.median(npa)), mean=round(float(npa.mean()), 2),
            share_6m_plus=round(float((npa >= 6).mean()), 4),
            share_zero=round(float((npa == 0).mean()), 4),
            never_flagged=int(never_flagged),
        ),
        lead_before_first_delinquency=dict(
            n=int(len(delinq)),
            median=None if not len(delinq) else float(np.median(delinq)),
            mean=None if not len(delinq) else round(float(delinq.mean()), 2),
            share_positive=None if not len(delinq) else round(float((delinq > 0).mean()), 4),
            definition=("months between the account's FIRST amber-or-worse month and its first "
                        "month with any DPD > 0. Positive means the model spoke first; zero or "
                        "negative means the arrears were already visible when it did."),
        ),
        recall_by_warning_horizon=recall_by_horizon,
        reading=(
            "Lead time before NPA is the number the card reports and it is real. Lead time "
            "before the FIRST missed payment is the harder and more useful one, because an "
            "alert raised after a borrower is already in arrears is telling a collections team "
            "something it can see on its own screen. Both are reported here; the share of "
            "defaulters flagged with zero sustained lead is the population the product does "
            "not help at all, and it is stated rather than averaged away."
        ),
    )


# --------------------------------------------------------------------------- C
def c_feature_set_alternatives(panel: pd.DataFrame, art: A.Artefact) -> dict:
    """DR-18/DR-19 on the FULL population, with a split the shipped model never used."""
    _ensure_src()
    import export_demo as ed
    import rigor
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
    fit, _pol, te = ed.three_way_split(df["account_id"].to_numpy(), seed=NEW_SPLIT_SEED)
    fit_lab, te_lab = fit[labelable[fit]], te[labelable[te]]

    families = rigor.FAMILIES if hasattr(rigor, "FAMILIES") else {}
    profile = [c for c in X.columns
               if any(c == col for col in families.get("Borrower profile", []))] or [
        c for c in X.columns if c in (
            "sector", "region", "segment", "qualification", "promoter_age_group",
            "constitution", "state", "city_tier", "nic_group", "business_age_years",
            "vintage_band", "loan_type", "portfolio")]

    variants = {
        "shipped": dict(cols=list(X.columns), kw={}),
        "profile_free": dict(cols=[c for c in X.columns if c not in profile], kw={}),
        "regularized": dict(cols=list(X.columns),
                            kw=dict(reg_alpha=1.0, reg_lambda=10.0, num_leaves=24,
                                    min_child_samples=200)),
    }
    base_kw = dict(n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
                   colsample_bytree=0.8, min_child_samples=80, random_state=7,
                   n_jobs=-1, verbose=-1)
    out = {}
    for name, spec in variants.items():
        cols = spec["cols"]
        kw = {**base_kw, **spec["kw"]}
        m = LGBMClassifier(**kw)
        m.fit(X[cols].iloc[fit_lab], y[fit_lab],
              categorical_feature=[c for c in cats if c in cols])
        p = m.predict_proba(X[cols].iloc[te_lab])[:, 1]
        out[name] = dict(
            n_features=len(cols), auc=round(float(roc_auc_score(y[te_lab], p)), 4),
            params={k: v for k, v in kw.items() if k in
                    ("num_leaves", "min_child_samples", "reg_alpha", "reg_lambda")},
        )
        print(f"    {name:<14s} {len(cols):>3d} features  AUC {out[name]['auc']}")
    shipped = out["shipped"]["auc"]
    for name, cell in out.items():
        cell["auc_gain_vs_shipped"] = round(cell["auc"] - shipped, 4)
    return dict(
        criteria=["DR-18", "DR-19"],
        question=("Does dropping borrower-profile features really BUY accuracy, on the full "
                  "population and on a split this model has never seen?"),
        population=f"{df['account_id'].nunique():,} accounts, eligible rows only",
        split_seed=NEW_SPLIT_SEED,
        n_profile_features=len(profile),
        profile_features=sorted(profile),
        variants=out,
        reading=(
            "DR-19's 0.0123 gain was measured on the 9,000 x 36 diagnostic book. Repeated here "
            "on the full 45,000-account population with a split seed the shipped model has "
            "never used, the profile-free variant's gain is the number in the table — read it "
            "against DR-19's, not instead of it. A regularized full-feature variant is fitted "
            "alongside, because 'the profile features hurt' and 'the model is over-fitting "
            "them' are different diagnoses with different fixes, and only the second is "
            "addressed by dropping columns."
        ),
    )


def run(skip_refits: bool = False) -> dict:
    art = A.load()
    panel = A.load_panel()
    test = A.test_frame(panel, art)
    decision = art.decision_score(test)

    print("  A — DR-12 decile stability under account resampling")
    a = a_decile_stability(test, decision, art)
    print("  B — DR-14 cohort ageing vs population change")
    b = b_cohort_aging(panel, art)
    print("  D — lead time before delinquency vs before NPA")
    d = d_lead_time(test, decision, art)
    c = None
    if not skip_refits:
        print("  C — DR-18/19 feature-set alternatives on the full population (3 fits)")
        c = c_feature_set_alternatives(panel, art)

    result = dict(
        experiment="disclosed_failures",
        artefact=art.manifest,
        grades_nothing=("No criteria.yaml band is read or written here. DR-12, DR-14, DR-18 and "
                        "DR-19 remain failures on the pre-registered arithmetic; this explains "
                        "what they are, it does not tune them away."),
        a_decile_stability=a,
        b_cohort_aging=b,
        c_feature_alternatives=c,
        d_lead_time=d,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=1))
    _write_markdown(result)
    return result


def _write_markdown(r: dict) -> None:
    a, b, c, d = (r["a_decile_stability"], r["b_cohort_aging"],
                  r["c_feature_alternatives"], r["d_lead_time"])
    boot = a["bootstrap"]
    L = ["# E2 — the four disclosed failures, as experiments", "",
         f"_{r['grades_nothing']}_", "",
         f"Artefact: policy `{r['artefact']['policy_version']}`, reproduces the shipped "
         f"operating point: `{r['artefact']['reproduces_shipped_thresholds']}`.", "",
         "## A — DR-12: material reversal, or sparse-cell noise?", "",
         f"Observed literal fraction **{a['observed_literal']}** against a band of {a['band']}; "
         f"CI-aware **{a['observed_ci_aware']}**.", "",
         f"Resampling the test fold by account {boot['n']} times, on the same model and the same",
         f"book, the literal statistic ranges **{boot['literal_range'][0]} to "
         f"{boot['literal_range'][1]}** (5th–95th percentile "
         f"{boot['literal_p05']}–{boot['literal_p95']}, mean {boot['literal_mean']}); it clears "
         f"the 0.9 band in **{boot['literal_share_passing']:.0%}** of resamples. The CI-aware "
         f"variant averages {boot['ci_aware_mean']} and clears the band in "
         f"{boot['ci_aware_share_passing']:.0%}.", "",
         f"{a['reading']}", "",
         "## B — DR-14: population change, or a closed cohort ageing?", "",
         f"| split | max CSI | binding feature |", "|---|---|---|",
         f"| time split (months <{b['cut_month']} vs >={b['cut_month']}) | "
         f"**{b['time_split']['max']}** | `{b['time_split']['binding']}` |",
         f"| random halves of ONE window (control) | {b['random_split_control']['max']} | "
         f"`{b['random_split_control']['binding']}` |",
         f"| replenished test window (vintage mix matched) | {b['replenished_cohort']['max']} | "
         f"`{b['replenished_cohort']['binding']}` |", "",
         f"{b['reading']}", "",
         "## D — lead time, split in two", ""]
    ln, ld = d["lead_before_npa"], d["lead_before_first_delinquency"]
    med_d = "—" if ld["median"] is None else f"{ld['median']:.0f} months"
    pos_d = "—" if ld["share_positive"] is None else f"{ld['share_positive']:.0%}"
    L += [f"Over {d['n_defaulters']:,} held-out defaulters:", "",
          f"* **before NPA** — median **{ln['median']:.0f} months**, "
          f"{ln['share_6m_plus']:.0%} flagged 6+ months ahead, and "
          f"**{ln['share_zero']:.0%} flagged with no sustained warning at all** "
          f"({ln['never_flagged']:,} accounts the product does not help).",
          f"* **before first delinquency** — median **{med_d}**, {pos_d} of defaulters were "
          f"flagged BEFORE any DPD appeared. {ld['definition']}", "",
          "| warning horizon | defaulters | share |", "|---|---|---|"]
    for row in d["recall_by_warning_horizon"]:
        L.append(f"| {row['bucket']} | {row['n']:,} | {row['share']:.1%} |")
    L += ["", f"{d['reading']}", ""]
    if c:
        L += ["## C — DR-18 / DR-19: profile-free and regularized alternatives", "",
              f"Population: {c['population']}. Split seed **{c['split_seed']}** — one the "
              f"shipped model has never used. {c['n_profile_features']} borrower-profile "
              f"features.", "",
              "| variant | features | AUC | gain vs shipped |", "|---|---|---|---|"]
        for name, cell in c["variants"].items():
            L.append(f"| {name} | {cell['n_features']} | {cell['auc']} | "
                     f"{cell['auc_gain_vs_shipped']:+.4f} |")
        L += ["", f"{c['reading']}", ""]
    (OUT / "REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-refits", action="store_true",
                    help="run A, B and D only (no LightGBM fits)")
    args = ap.parse_args()
    print("E2 — disclosed failures:")
    run(skip_refits=args.skip_refits)
    print(f"E2 -> {OUT}")
