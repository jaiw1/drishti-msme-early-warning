"""
Scoring + explanation pipeline  ->  data/demo_data.json  (consumed by the React cockpit)

Trains the final early-warning model on the synthetic panel, then for the held-out
(out-of-sample) accounts produces everything the UI needs:
  * per-month probability-of-default (PD) score  -> the deterioration TIMELINE
  * plain-language REASON CODES (from LightGBM feature contributions / SHAP-style)
  * RAG buckets (red / amber / green)
  * portfolio KPIs, recall@budget, recall-by-lead-time, AUC/KS  (the honest metrics)
  * auto-drafted SMA/CRILC-style alert memo for red accounts

The "current book" is frozen at a fixed reference month (REF_MONTH) = "today", so the
book shows accounts at VARYING distances from trouble — some flagged amber ~a year out
(the early-warning value), some red just before NPA. Everything is baked to JSON so the
deployed app has NO live-backend dependency and cannot fail on stage.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import roc_auc_score, average_precision_score, roc_curve

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so `generator` imports

from generator.portfolios import ALL_CHANNELS, PORTFOLIOS   # noqa: E402  (path shim first)

ROOT = __file__.rsplit("/src/", 1)[0]
PANEL = f"{ROOT}/data/msme_loan_panel.csv"
OUT = f"{ROOT}/data/demo_data.json"
REF_MONTH = 24                       # "today" for the frozen portfolio snapshot

# The five SD-D2 statics are CATEGORICAL, not numeric: without them LightGBM raises
# "pandas dtypes must be int, float or bool" on the eight-portfolio panel. `secured`,
# `tenor_months` and `interest_rate_pa` are genuinely numeric and stay out.
CAT = ["sector", "region", "loan_type", "segment", "qualification", "promoter_age_group"]
CAT += ["portfolio", "constitution", "state", "city_tier", "nic_group"]
# Every FORWARD-LOOKING column is dropped here or the model trains on the answer.
# `sma2_within_6m` (SD-D5) is a label, not a feature: it says whether the account
# reaches 61-90 DPD in the NEXT six months. A test pins this list against the
# generator's own declaration, so a label added later cannot slip into training.
DROP = ["account_id", "month_idx", "date",
        "default_within_12m", "sma2_within_6m", "labelable", "months_to_npa"]

#: contract portfolio code -> the observation channels that portfolio actually has.
#: A column belonging to a channel a portfolio does not declare is NaN in the panel and
#: must reach the UI as `null` + an absent channel, never as a zero.
CHANNELS_BY_PORTFOLIO: dict[str, list[str]] = {
    p.code: list(p.channels) for p in PORTFOLIOS.values()
}

HUMAN = {  # feature -> (value -> human string, or None if not noteworthy for this row)
    "inflow_vs_6m_avg":          lambda v: f"Bank inflows {abs(v)*100:.0f}% below 6-month average" if v < -0.08 else None,
    "inflow_trend_3m":           lambda v: f"Cash inflows down {abs(v)*100:.0f}% over 3 months" if v < -0.08 else None,
    "sales_trend_3m":            lambda v: f"GST sales down {abs(v)*100:.0f}% over 3 months" if v < -0.08 else None,
    "utilisation":               lambda v: f"Credit-limit use high ({v*100:.0f}%)" if v > 0.75 else None,
    "util_avg_3m":               lambda v: f"Sustained high utilisation ({v*100:.0f}%, 3m avg)" if v > 0.75 else None,
    "util_max_6m":               lambda v: f"Peaked near credit limit ({v*100:.0f}%)" if v > 0.85 else None,
    "months_over_90pct_util_6m": lambda v: f"Near credit limit in {int(v)} of last 6 months" if v >= 1 else None,
    "dpd":                       lambda v: f"Currently {int(v)} days past due" if v > 0 else None,
    "dpd_max_6m":                lambda v: f"Late payment in last 6 months ({int(v)} days)" if v > 0 else None,
    "times_late_6m":             lambda v: f"{int(v)} late-payment month(s) in last 6" if v > 0 else None,
    "bounces_6m":                lambda v: f"{int(v)} bounced payment(s) in 6 months" if v > 0 else None,
    "minbal_breach_6m":          lambda v: f"Min-balance breached {int(v)}x in 6 months" if v > 0 else None,
    "txn_drop_flag":             lambda v: "Transaction volume dropped sharply" if v > 0 else None,
    "adverse_remark_6m":         lambda v: "Adverse remark flagged in filings" if v > 0 else None,
    "vintage_months":            lambda v: "New borrower relationship (<1 yr)" if v < 12 else None,
    "business_age_years":        lambda v: "Young business (<3 yrs)" if v < 3 else None,
    "log_sanctioned":            lambda v: "Large loan exposure" if v > 16.1 else None,
    # segment factors: only surface when genuinely higher-risk (never flag a benign value)
    "sector":                    lambda v: f"Higher-risk sector ({v})" if v in ("Trading", "Retail", "Logistics") else None,
    "region":                    lambda v: None,
    "loan_type":                 lambda v: None,
    "promoter_age_group":        lambda v: f"Promoter age band {v}" if v in ("<30", "60+") else None,
    "qualification":             lambda v: f"Thin promoter profile ({v})" if v in ("SchoolOnly", "UnderGrad") else None,
    # --- eight-portfolio channels (SD-D3). A channel a portfolio does not have is NaN,
    # and every comparison below is False on NaN, so an absent channel simply never
    # produces a reason code — it is not silently read as zero.
    "collection_ratio":          lambda v: f"Only {v*100:.0f}% of the amount demanded was collected" if v < 0.95 else None,
    "collection_ratio_3m":       lambda v: f"Short collection sustained ({v*100:.0f}% of demand, 3m avg)" if v < 0.95 else None,
    "salary_vs_6m_avg":          lambda v: f"Salary credit {abs(v)*100:.0f}% below 6-month average" if v < -0.08 else None,
    "salary_gap_6m":             lambda v: f"No salary credit in {int(v)} of last 6 months" if v >= 1 else None,
    "emi_burden_ratio":          lambda v: f"EMI outgo is {v*100:.0f}% of inflow" if v > 0.50 else None,
    "other_bank_emi":            lambda v: "Servicing EMIs to other lenders" if v > 0 else None,
    "ltv_vs_schedule":           lambda v: f"Loan-to-value {v*100:.0f}% above its scheduled level" if v > 0.03 else None,
    "ltv":                       lambda v: f"High loan-to-value ({v*100:.0f}%)" if v > 0.85 else None,
    "rental_vs_6m_avg":          lambda v: f"Rental income {abs(v)*100:.0f}% below 6-month average" if v < -0.08 else None,
    "crop_receipt_vs_norm":      lambda v: f"Crop receipts {abs(v)*100:.0f}% below the seasonal norm" if v < -0.08 else None,
    "renewal_overdue_months":    lambda v: f"KCC renewal overdue by {int(v)} month(s)" if v >= 1 else None,
    "commute_vs_6m_avg":         lambda v: f"Commute/fuel spend {abs(v)*100:.0f}% below 6-month average" if v < -0.15 else None,
    "months_since_moratorium_end": lambda v: f"First demands after moratorium ({int(v)} month(s) in)" if 0 <= v <= 6 else None,
    "min_balance_6m":            lambda v: None,
    "bureau_score":              lambda v: f"Bureau score {int(v)} (sub-prime)" if v < 650 else None,
}


# --------------------------------------------------------------------------- #
# JSON-safety. The panel is deliberately sparse: a column belonging to a channel a
# portfolio does not have is NaN, and ~55% of accounts carry at least one such column.
# `float(nan)` reaches json.dump as a bare `NaN` literal, which is NOT valid JSON —
# the React app's JSON.parse() rejects it and the whole cockpit fails to load. Every
# number pulled out of the snapshot goes through these.
# --------------------------------------------------------------------------- #
def jnum(value, places=None):
    """A snapshot value as a JSON-safe float, or ``None`` when it is not observed."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return round(v, places) if places is not None else v


def jint(value):
    """A snapshot value as a JSON-safe int, or ``None`` when it is not observed."""
    v = jnum(value)
    return None if v is None else int(v)


def channels_present(portfolio_code):
    """The observation channels this portfolio declares.

    The UI reads this to tell "not applicable" (no such channel for this product)
    apart from "observed, and it was zero". A portfolio the registry does not know —
    e.g. a legacy single-portfolio panel — is assumed to carry everything.
    """
    return CHANNELS_BY_PORTFOLIO.get(str(portfolio_code), list(ALL_CHANNELS))


def ks_stat(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


RANK_HORIZON = 8  # 7–8 month window: subsequent NPA rate by score (rank-order check)
BANDS = (("Green", "green"), ("Amber", "amber"), ("Red", "red"))
Z95 = 1.959963984540054
#: DR-12's pre-registered floor: the share of decile step-ups that must be
#: non-decreasing. Ten deciles give NINE steps, so 0.9 means all nine of them.
DECILE_STEP_FLOOR = 0.9


def wilson(k, n, z=Z95):
    """95% Wilson score interval for ``k`` of ``n``.

    Wilson rather than the normal approximation because these cells are small and
    often have zero defaults, where the normal interval collapses to a point and
    would overstate what a 40-account Red band in one portfolio actually proves.
    """
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _rate_cell(k, n):
    lo, hi = wilson(k, n)
    return dict(n=int(n), defaults=int(k), bad_rate=round(k / n, 4) if n else 0.0,
                ci_lo=round(lo, 4), ci_hi=round(hi, 4))


def _went_bad(frame, horizon):
    """Boolean array: did this snapshot account reach NPA within `horizon` months?"""
    mtn = frame["snap_months_to_npa"].to_numpy()
    return (mtn >= 1) & (mtn <= horizon)


def _by_band(frame, horizon):
    went = _went_bad(frame, horizon)
    rows = []
    for name, key in BANDS:
        mask = (frame.bucket == key).to_numpy()
        rows.append(dict(band=name, **_rate_cell(int(went[mask].sum()), int(mask.sum()))))
    return rows


def _by_decile(frame, horizon):
    ranked = frame.sort_values("pd").reset_index(drop=True)
    went = _went_bad(ranked, horizon)
    n = len(ranked)
    rows = []
    for i in range(10):
        lo, hi = int(i * n / 10), int((i + 1) * n / 10)
        sl = ranked.iloc[lo:hi]
        m = len(sl)
        rows.append(dict(
            decile=i + 1,
            pd_lo=jnum(sl.pd.min(), 4) if m else 0.0,
            pd_hi=jnum(sl.pd.max(), 4) if m else 0.0,
            **_rate_cell(int(went[lo:hi].sum()), m),
        ))
    return rows


def _monotone_bands(bands):
    """DR-11: STRICTLY increasing Green -> Amber -> Red. Ties fail, by design."""
    rates = [b["bad_rate"] for b in bands]
    return all(a < b for a, b in zip(rates, rates[1:]))


def _decile_steps(deciles):
    """DR-12: how many of the nine decile step-ups are non-decreasing."""
    rates = [d["bad_rate"] for d in deciles]
    steps = list(zip(rates, rates[1:]))
    return sum(1 for a, b in steps if b >= a), len(steps)


def _exhibit_cell(frame, horizon, portfolio=None):
    """One rank-order panel — pooled, or one portfolio's.

    Every cell is self-contained (`by_band` + `by_decile` + its own verdicts), so the
    UI can render the pooled exhibit and the eight small multiples with one component.
    """
    bands = _by_band(frame, horizon)
    deciles = _by_decile(frame, horizon)
    ok, total = _decile_steps(deciles)
    red = next(b for b in bands if b["band"] == "Red")
    cell = dict(
        n=int(len(frame)),
        by_band=bands,
        by_decile=deciles,
        # DM-4's hook: Red-band precision at 8 months IS the Red band's realised bad
        # rate on this table, so it is emitted here with its CI rather than recomputed.
        red_band_precision_8m=dict(
            n=red["n"], hits=red["defaults"], precision=red["bad_rate"],
            ci_lo=red["ci_lo"], ci_hi=red["ci_hi"],
        ),
        bands_monotone=_monotone_bands(bands),
        monotone_decile_steps=ok,
        decile_steps=total,
        monotone_decile_step_fraction=round(ok / total, 4) if total else 0.0,
    )
    if portfolio is not None:
        cell["portfolio"] = portfolio
        cell["title"] = f"{portfolio} — do high-risk flags actually go bad?"
    return cell


def rank_order_exhibit(port_df, horizon=RANK_HORIZON):
    """Realised NPA rate over `horizon` months, by RAG band and by score decile.

    An account is a subsequent NPA if months-to-NPA at the snapshot is in 1..horizon.
    Computed on the same frozen book the cockpit shows — not a second cut of the panel.

    The pooled exhibit stays at the top level (unchanged shape). ``by_portfolio``
    repeats the whole exhibit for each of the eight portfolios, because the mentors'
    mandate is that rank order holds *within every borrower type*, not on average —
    one holistic model is only defensible if none of the eight is carried by the rest.
    """
    exhibit = dict(
        horizon_months=horizon,
        definition=("Share of snapshot accounts that reach NPA (90+ DPD) within the next "
                    f"{horizon} months, by model risk band and by score decile."),
        population="held-out accounts in the frozen book at the reference month",
        **_exhibit_cell(port_df, horizon),
    )
    by_portfolio = []
    if "portfolio" in port_df.columns:
        for code in [p.code for p in PORTFOLIOS.values()]:
            sub = port_df[port_df.portfolio == code]
            if not len(sub):
                continue
            by_portfolio.append(_exhibit_cell(sub, horizon, portfolio=code))
    exhibit["by_portfolio"] = by_portfolio
    return exhibit


def format_rank_order(exhibit):
    """The exhibit as printable lines — emitted before the assertion, so a failure
    arrives with the table that caused it rather than just a verdict."""
    lines = []
    for label, cell in [("POOLED", exhibit)] + [(c["portfolio"], c) for c in exhibit["by_portfolio"]]:
        bands = " | ".join(
            f"{b['band']} {b['bad_rate']:.1%} [{b['ci_lo']:.1%}-{b['ci_hi']:.1%}] ({b['defaults']}/{b['n']})"
            for b in cell["by_band"])
        lines.append(f"  {label:<18s} n={cell['n']:<6d} {bands}")
        lines.append(f"  {'':<18s} deciles " + " ".join(f"{d['bad_rate']:.1%}" for d in cell["by_decile"])
                     + f"  monotone {cell['monotone_decile_steps']}/{cell['decile_steps']}"
                     + ("  BANDS OK" if cell["bands_monotone"] else "  BANDS NOT MONOTONE"))
    return lines


def rank_order_violations(exhibit):
    """Every DR-11 / DR-12 cell this exhibit fails, as human-readable strings."""
    failures = []
    cells = [("pooled", exhibit)] + [(c["portfolio"], c) for c in exhibit["by_portfolio"]]
    for label, cell in cells:
        if not cell["bands_monotone"]:
            rates = " -> ".join(f"{b['band']} {b['bad_rate']:.4f} (n={b['n']})" for b in cell["by_band"])
            failures.append(f"DR-11 {label}: band default rates not strictly increasing: {rates}")
        if cell["monotone_decile_step_fraction"] < DECILE_STEP_FLOOR:
            rates = " ".join(f"{d['bad_rate']:.4f}" for d in cell["by_decile"])
            failures.append(
                f"DR-12 {label}: only {cell['monotone_decile_steps']}/{cell['decile_steps']} decile steps "
                f"non-decreasing (floor {DECILE_STEP_FLOOR:.0%}): {rates}")
    return failures


def assert_rank_order(exhibit):
    """DR-11 + DR-12, asserted in-script: bands strictly monotone within EVERY portfolio
    (and pooled), and at least 90% of decile step-ups non-decreasing.

    Raises:
        AssertionError: listing every cell that failed, with its numbers.
    """
    failures = rank_order_violations(exhibit)
    if failures:
        raise AssertionError(
            f"rank-order exhibit failed at horizon {exhibit['horizon_months']} months "
            f"({len(failures)} violation(s)):\n  " + "\n  ".join(failures))


def reason_codes(feat_row, contribs, cols, k=3):
    """Top-k risk-increasing, human-readable drivers for one account-month.

    An unobserved feature never produces a reason code. That has to be stated once,
    here, rather than left to each rule: a float NaN quietly compares False, but the
    panel's whole-number channel columns are pandas' nullable ``Int64``, whose NA
    *raises* on comparison ("boolean value of NA is ambiguous"). Both mean the same
    thing — the bank has no such number for this product — and both must be skipped.
    """
    out = []
    for c, contrib in sorted(zip(cols, contribs), key=lambda x: -x[1]):
        if contrib <= 0 or c not in HUMAN:
            continue
        value = feat_row[c]
        if pd.isna(value):
            continue
        s = HUMAN[c](value)
        if s:
            out.append(s)
        if len(out) >= k:
            break
    return out


def build_export(df, static, ref_month=REF_MONTH, horizon=RANK_HORIZON):
    """Train, score and assemble the whole cockpit payload from an in-memory panel.

    Split out of ``main`` so the pipeline can be exercised end to end on a small panel
    (the JSON-validity and channel tests do exactly that) and so the DM-6 ``--bank``
    path has one place to inject an enriched frame.

    Args:
        df: the account-month panel.
        static: ``accounts_static``, indexed by ``account_id``.
        ref_month: the ``month_idx`` the frozen book is taken at.
        horizon: months ahead for the rank-order exhibit.

    Returns:
        The payload dict. It is JSON-valid: no NaN, no infinity, anywhere.
    """
    cats = [c for c in CAT if c in df.columns]
    for c in cats:
        df[c] = df[c].astype("category")
    y = df["default_within_12m"].values
    X = df.drop(columns=DROP)
    cols = list(X.columns)

    gss = GroupShuffleSplit(n_splits=1, test_size=0.30, random_state=7)
    tr, te = next(gss.split(X, y, groups=df["account_id"]))

    model = LGBMClassifier(
        n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
        colsample_bytree=0.8, min_child_samples=80, random_state=7, n_jobs=-1, verbose=-1,
    )
    model.fit(X.iloc[tr], y[tr], categorical_feature=cats)

    te_df = df.iloc[te].copy().reset_index(drop=True)
    Xte = X.iloc[te].reset_index(drop=True)
    p = model.predict_proba(Xte)[:, 1]
    te_df["pd"] = p
    te_df["pos"] = np.arange(len(te_df))                              # row -> contrib index
    contribs = model.booster_.predict(Xte, pred_contrib=True)[:, :-1]

    # ---- honest metrics (row level, over all test account-months) ----
    yte = te_df["default_within_12m"].values
    auc, prauc, ks = roc_auc_score(yte, p), average_precision_score(yte, p), ks_stat(yte, p)

    def recall_at(budget):
        k = max(1, int(len(p) * budget))
        return float(yte[np.argsort(p)[::-1][:k]].sum() / max(1, yte.sum()))

    thr10 = float(np.quantile(p, 0.90))
    lead_curve = []
    for lo, hi in [(1, 3), (4, 6), (7, 9), (10, 12)]:
        m = (te_df.default_within_12m == 1) & te_df.months_to_npa.between(lo, hi)
        lead_curve.append(dict(bucket=f"{lo}-{hi} mo",
                               recall=round(float((te_df.loc[m, "pd"] >= thr10).mean()), 3) if int(m.sum()) else 0.0))

    # ---- smoothed risk trajectory (3-month trailing mean) ----
    # A real early-warning desk acts on a smoothed risk TREND, not a jittery single-month
    # score. Smoothing removes one-off blips and widens the "sliding/amber" tier.
    te_df = te_df.sort_values(["account_id", "month_idx"]).reset_index(drop=True)
    te_df["pd_smooth"] = te_df.groupby("account_id")["pd"].transform(lambda s: s.rolling(4, min_periods=1).mean())

    # ---- interpretable RAG thresholds on the smoothed PD ----
    RED_THR, AMBER_THR = 0.40, 0.04          # >=40% default prob = Red (act) ; >=4% = Amber (watch)
    red_thr, amber_thr = RED_THR, AMBER_THR
    snap = te_df[te_df.month_idx == ref_month].copy()
    bucket = lambda s: "red" if s >= red_thr else "amber" if s >= amber_thr else "green"

    # ---- SUSTAINED first-warning lead time per account ----
    # Honest lead = length of the FINAL uninterrupted amber+ run before NPA (within the
    # 12-month horizon). Using the sustained run — not any single blip — avoids crediting
    # a one-off spike as an "early warning".
    def sustained_lead(g):
        g = g.sort_values("month_idx")
        flagged = (g["pd_smooth"] >= amber_thr).values
        mtn = g["months_to_npa"].values
        lead = 0
        for f, m in zip(flagged[::-1], mtn[::-1]):        # walk backward from the last pre-NPA month
            if f and 1 <= m <= 12:
                lead = m
            elif m <= 12:
                break                                      # run broke inside the horizon -> stop
        return lead
    first_warn = te_df.groupby("account_id").apply(sustained_lead, include_groups=False)

    # ---- portfolio = frozen snapshot at REF_MONTH ----
    portfolio = []
    for _, cur in snap.iterrows():
        acc_id, pos = cur["account_id"], int(cur["pos"])
        st = static.loc[acc_id]
        code = str(cur["portfolio"]) if "portfolio" in snap.columns else ""
        portfolio.append(dict(
            account_id=acc_id, sector=str(cur["sector"]), region=str(cur["region"]),
            loan_type=str(cur["loan_type"]), segment=str(cur["segment"]),
            promoter_age_group=str(cur["promoter_age_group"]),
            # SD-D2 statics: the cockpit's portfolio cut, and what channels_present keys off
            portfolio=code,
            constitution=str(cur["constitution"]) if "constitution" in snap.columns else "",
            secured=bool(cur["secured"]) if pd.notna(cur.get("secured")) else None,
            sanctioned=float(round(np.exp(cur["log_sanctioned"]))),
            vintage_months=jint(cur["vintage_months"]), business_age_years=jint(st["business_age_years"]),
            pd=jnum(cur["pd_smooth"], 4), bucket=bucket(cur["pd_smooth"]),
            # channel-gated: `null` means "this product has no such channel", NOT zero.
            dpd=jnum(cur["dpd"], 1), utilisation=jnum(cur["utilisation"], 3),
            inflow_vs_6m_avg=jnum(cur["inflow_vs_6m_avg"], 3),
            sales_trend_3m=jnum(cur["sales_trend_3m"], 3),
            collection_ratio=jnum(cur.get("collection_ratio"), 3),
            salary_vs_6m_avg=jnum(cur.get("salary_vs_6m_avg"), 3),
            bureau_score=jint(cur.get("bureau_score")),
            channels_present=channels_present(code),
            reasons=reason_codes(Xte.iloc[pos], contribs[pos], cols),
            first_warning_lead=jint(first_warn.get(acc_id, 0)) or 0,
            snap_months_to_npa=jint(cur["months_to_npa"]) if pd.notna(cur["months_to_npa"]) else -1,
            ground_truth_default=int(st["is_defaulter"]),          # demo "outcome" reveal only
        ))
    port_df = pd.DataFrame(portfolio)

    # ---- ecosystem-stress lens (trading-partner linkage) ----
    # Stress travels through trading networks: a supplier's default becomes its buyers'
    # cash-flow problem. We build an illustrative linkage layer (real deployment plugs in
    # CRILC exposures / GST buyer-supplier graphs): every account gets 2-4 partners drawn
    # mostly from its own sector, and every RED account additionally "anchors" 2-4
    # dependents — because real distress clusters, it doesn't scatter.
    # The model PD is NOT altered — this is a second, network lens the officer sees.
    rng_l = np.random.default_rng(42)
    ids = list(port_df.account_id)
    idx = {a: i for i, a in enumerate(ids)}
    by_sector = {s: list(g.account_id) for s, g in port_df.groupby("sector")}
    by_region = {s: list(g.account_id) for s, g in port_df.groupby("region")}
    bucket_of = dict(zip(port_df.account_id, port_df.bucket))
    links = {a: set() for a in ids}
    for rec in portfolio:
        aid = rec["account_id"]
        pool_s, pool_r = by_sector[rec["sector"]], by_region[rec["region"]]
        want = int(rng_l.integers(2, 5))
        guard = 0
        while len(links[aid]) < want and guard < 40:
            guard += 1
            pool = pool_s if rng_l.random() < 0.7 else pool_r
            c = pool[int(rng_l.integers(0, len(pool)))]
            if c != aid:
                links[aid].add(c); links[c].add(aid)
    for rec in portfolio:                       # red anchors pull dependents in
        if rec["bucket"] == "red":
            pool = by_sector[rec["sector"]]
            for _ in range(int(rng_l.integers(2, 5))):
                c = pool[int(rng_l.integers(0, len(pool)))]
                if c != rec["account_id"]:
                    links[rec["account_id"]].add(c); links[c].add(rec["account_id"])
    for rec in portfolio:
        ps = links[rec["account_id"]]
        rec["eco_partners"] = len(ps)
        rec["eco_flagged"] = sum(1 for p in ps if bucket_of[p] != "green")
        rec["eco_red"] = sum(1 for p in ps if bucket_of[p] == "red")
    green_1link = [r for r in portfolio if r["bucket"] == "green" and r["eco_red"] >= 1]
    amber_1link = [r for r in portfolio if r["bucket"] == "amber" and r["eco_red"] >= 1]
    eco_sector = {}
    for r in green_1link + amber_1link:
        e = eco_sector.setdefault(r["sector"], dict(sector=r["sector"], n=0, exposure=0.0))
        e["n"] += 1; e["exposure"] += r["sanctioned"]
    ecosystem = dict(
        n_green_1link_red=len(green_1link), n_amber_1link_red=len(amber_1link),
        exposure_1link_red=float(sum(r["sanctioned"] for r in green_1link + amber_1link)),
        by_sector=sorted(eco_sector.values(), key=lambda x: -x["exposure"])[:6],
    )
    print(f"ecosystem: {len(green_1link)} green + {len(amber_1link)} amber accounts within 1 link of a red "
          f"(₹{ecosystem['exposure_1link_red']/1e7:.1f} cr exposure)")

    # ---- spotlight accounts (present in snapshot) with full timelines ----
    # lead with "caught early, still has runway": amber today, NPA still 6-12 months away
    caught_early = port_df[(port_df.bucket == "amber") & (port_df.ground_truth_default == 1)
                           & (port_df.snap_months_to_npa.between(6, 12))].sort_values("snap_months_to_npa", ascending=False)
    reds_def = port_df[(port_df.bucket == "red") & (port_df.ground_truth_default == 1)] \
        .sort_values("first_warning_lead", ascending=False)
    healthy = port_df[(port_df.bucket == "green") & (port_df.ground_truth_default == 0)]
    pick = (list(caught_early.account_id.head(4)) + list(reds_def.account_id.head(4))
            + list(healthy.account_id.head(3)))
    pick = list(dict.fromkeys(pick))   # dedupe, preserve order

    spotlight_ids = pick

    # ---- timelines for EVERY account in the book (so ANY clicked account renders) ----
    port_ids = set(port_df.account_id)
    tcols = ["account_id", "month_idx", "date", "pd", "pd_smooth", "utilisation", "inflow"]
    timelines = {}
    for acc_id, g in te_df[te_df.account_id.isin(port_ids)][tcols].sort_values("month_idx").groupby("account_id"):
        # `utilisation` is null on the five portfolios with no credit limit — the chart
        # must draw a gap there, not a line along zero.
        timelines[acc_id] = [dict(date=d, pd=jnum(p, 3), pd_smooth=jnum(ps, 3),
                                  utilisation=jnum(u, 3), inflow=jint(inf))
                             for d, p, ps, u, inf in
                             zip(g.date, g.pd, g.pd_smooth, g.utilisation, g.inflow)]

    # ---- auto-drafted memo for EVERY red account ----
    memos = {}
    for rec in portfolio:
        if rec["bucket"] == "red":
            memos[rec["account_id"]] = (
                f"SMA / EARLY-WARNING ALERT — Account {rec['account_id']}\n"
                f"Facility: {rec['loan_type']} | Sanctioned: ₹{rec['sanctioned']:,.0f} | Sector: {rec['sector']}\n"
                f"Model PD (12-month): {rec['pd']*100:.0f}%  [RED]\n"
                f"Primary early-warning signals:\n  - " + "\n  - ".join(rec["reasons"] or ["elevated model risk"]) + "\n"
                f"Recommended action: classify SMA-1, initiate borrower engagement, review working-capital "
                f"cycle and GST filings; escalate to relationship manager. (AI-generated — human review required.)"
            )

    # aggregate lead-time stats over ALL held-out defaulters (model capability, not just the snapshot)
    te_def_ids = [a for a in te_df.account_id.unique() if int(static.loc[a, "is_defaulter"]) == 1]
    lead_series = first_warn.reindex(te_def_ids).fillna(0)

    rigor = {}
    try:
        rigor = json.load(open(f"{ROOT}/data/rigor.json"))     # produced by src/rigor.py
    except Exception:
        pass

    n_accounts = int(df.account_id.nunique())
    n_months = int(df.month_idx.nunique())
    rank_order = rank_order_exhibit(port_df, horizon=horizon)
    # The gate's verdict travels INSIDE the payload as well as being asserted by the
    # CLI, so an artefact produced by a failing run can never be mistaken for a passing
    # one — the cockpit and the honesty gate both read it off the file itself.
    violations = rank_order_violations(rank_order)
    rank_order["gate"] = dict(criteria=["DR-11", "DR-12"], passed=not violations,
                              violations=violations)
    out = dict(
        meta=dict(
            generated_from=(f"synthetic retail/MSME loan panel ({n_accounts:,} accounts x "
                            f"{n_months} months, {len(CHANNELS_BY_PORTFOLIO)} portfolios); "
                            "model=LightGBM"),
            reference_month=str(snap["date"].iloc[0]), horizon_months=12, npa_definition_dpd=90,
            n_accounts_scored=int(port_df.account_id.nunique()),
            # so the UI can say "not applicable" without re-deriving the rule per account
            channels=list(ALL_CHANNELS),
            channels_by_portfolio=CHANNELS_BY_PORTFOLIO,
        ),
        metrics=dict(
            auc=round(auc, 3), pr_auc=round(prauc, 3), ks=round(ks, 3),
            recall_at_budget=[dict(budget=b, recall=round(recall_at(b), 3)) for b in (0.02, 0.05, 0.10, 0.20)],
            recall_by_lead_time=lead_curve,
            median_first_warning_months=jint(lead_series.median()) or 0,
            pct_flagged_6mo_ahead=jnum((lead_series >= 6).mean(), 3) or 0.0,
            rank_order=rank_order,
        ),
        portfolio_summary=dict(
            total_accounts=len(port_df),
            red=int((port_df.bucket == "red").sum()), amber=int((port_df.bucket == "amber").sum()),
            green=int((port_df.bucket == "green").sum()),
            exposure_at_risk=float(port_df.loc[port_df.bucket == "red", "sanctioned"].sum()),
            red_thr=round(red_thr, 4), amber_thr=round(amber_thr, 4),
        ),
        portfolio=portfolio, spotlight=spotlight_ids, timelines=timelines, memos=memos,
        ecosystem=ecosystem,
        rigor=rigor,
    )
    return out


def main():
    df = pd.read_csv(PANEL)
    static = pd.read_csv(f"{ROOT}/data/accounts_static.csv").set_index("account_id")
    out = build_export(df, static)
    rank_order = out["metrics"]["rank_order"]

    s = out["portfolio_summary"]
    m = out["metrics"]
    print(f"AUC {m['auc']:.3f} | KS {m['ks']:.3f} | PR-AUC {m['pr_auc']:.3f}  | ref month = {out['meta']['reference_month']}")
    print(f"book: {s['total_accounts']} accts  ->  RED {s['red']} / AMBER {s['amber']} / GREEN {s['green']}")
    print(f"exposure at risk (red): ₹{s['exposure_at_risk']:,.0f}")
    print(f"spotlight w/ timelines: {len(out['spotlight'])}")
    print(f"median first-warning lead: {m['median_first_warning_months']} mo | >=6mo: {m['pct_flagged_6mo_ahead']:.0%}")
    print(f"rank-order at {rank_order['horizon_months']} months (realised NPA rate, 95% Wilson CI):")
    for line in format_rank_order(rank_order):
        print(line)
    rbp = rank_order["red_band_precision_8m"]
    print(f"RED-BAND PRECISION @8mo (pooled): {rbp['precision']:.1%} "
          f"[{rbp['ci_lo']:.1%}-{rbp['ci_hi']:.1%}]  ({rbp['hits']}/{rbp['n']})")

    recall10 = next(r["recall"] for r in m["recall_at_budget"] if r["budget"] == 0.10)
    with open(OUT, "w") as f:
        # allow_nan=False is the guard, not a nicety: json.dump would otherwise write
        # bare `NaN` literals, which are not JSON and which the cockpit cannot parse.
        json.dump(out, f, allow_nan=False)
    print(f"recall@10% budget: {recall10:.0%} | wrote {OUT} ({len(json.dumps(out))/1024:.0f} KB)")

    # DR-11 / DR-12 gate, LAST: the file and the table are written first so a failure
    # arrives with the evidence that caused it and the other lanes still have a shape to
    # build against — but the process exits non-zero, and the payload it wrote says
    # `rank_order.gate.passed == false`, so a failing panel can never quietly ship.
    assert_rank_order(rank_order)


if __name__ == "__main__":
    main()
