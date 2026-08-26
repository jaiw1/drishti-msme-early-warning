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
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import roc_auc_score, average_precision_score, roc_curve

ROOT = __file__.rsplit("/src/", 1)[0]
PANEL = f"{ROOT}/data/msme_loan_panel.csv"
OUT = f"{ROOT}/data/demo_data.json"
REF_MONTH = 24                       # "today" for the frozen portfolio snapshot

CAT = ["sector", "region", "loan_type", "segment", "qualification", "promoter_age_group"]
DROP = ["account_id", "month_idx", "date", "default_within_12m", "labelable", "months_to_npa"]

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
}


def ks_stat(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


RANK_HORIZON = 8  # 7–8 month window: subsequent NPA rate by score (rank-order check)


def rank_order_exhibit(port_df, horizon=RANK_HORIZON):
    """Realised NPA rate over `horizon` months, by RAG band and by score decile.

    An account is a subsequent NPA if months-to-NPA at the snapshot is in 1..horizon.
    Computed on the same frozen book the cockpit shows — not a second cut of the panel.
    """
    mtn = port_df["snap_months_to_npa"]
    went = (mtn >= 1) & (mtn <= horizon)
    bands = []
    for name, key in (("Green", "green"), ("Amber", "amber"), ("Red", "red")):
        mask = port_df.bucket == key
        n = int(mask.sum())
        k = int(went[mask].sum())
        bands.append(dict(band=name, n=n, defaults=k,
                          bad_rate=round(k / n, 4) if n else 0.0))
    ranked = port_df.sort_values("pd").reset_index(drop=True)
    n = len(ranked)
    deciles = []
    for i in range(10):
        lo, hi = int(i * n / 10), int((i + 1) * n / 10)
        sl = ranked.iloc[lo:hi]
        k = int(((sl.snap_months_to_npa >= 1) & (sl.snap_months_to_npa <= horizon)).sum())
        deciles.append(dict(
            decile=i + 1, n=int(len(sl)),
            pd_lo=round(float(sl.pd.min()), 4), pd_hi=round(float(sl.pd.max()), 4),
            defaults=k, bad_rate=round(k / len(sl), 4) if len(sl) else 0.0,
        ))
    return dict(
        horizon_months=horizon,
        definition=("Share of snapshot accounts that reach NPA (90+ DPD) within the next "
                    f"{horizon} months, by model risk band and by score decile."),
        by_band=bands, by_decile=deciles,
    )


def reason_codes(feat_row, contribs, cols, k=3):
    """Top-k risk-increasing, human-readable drivers for one account-month."""
    out = []
    for c, contrib in sorted(zip(cols, contribs), key=lambda x: -x[1]):
        if contrib <= 0 or c not in HUMAN:
            continue
        s = HUMAN[c](feat_row[c])
        if s:
            out.append(s)
        if len(out) >= k:
            break
    return out


def main():
    df = pd.read_csv(PANEL)
    for c in CAT:
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
    model.fit(X.iloc[tr], y[tr], categorical_feature=CAT)

    te_df = df.iloc[te].copy().reset_index(drop=True)
    Xte = X.iloc[te].reset_index(drop=True)
    p = model.predict_proba(Xte)[:, 1]
    te_df["pd"] = p
    te_df["pos"] = np.arange(len(te_df))                              # row -> contrib index
    contribs = model.booster_.predict(Xte, pred_contrib=True)[:, :-1]
    static = pd.read_csv(f"{ROOT}/data/accounts_static.csv").set_index("account_id")

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
    snap = te_df[te_df.month_idx == REF_MONTH].copy()
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
        portfolio.append(dict(
            account_id=acc_id, sector=str(cur["sector"]), region=str(cur["region"]),
            loan_type=str(cur["loan_type"]), segment=str(cur["segment"]),
            promoter_age_group=str(cur["promoter_age_group"]),
            sanctioned=float(round(np.exp(cur["log_sanctioned"]))),
            vintage_months=int(cur["vintage_months"]), business_age_years=int(st["business_age_years"]),
            pd=round(float(cur["pd_smooth"]), 4), bucket=bucket(cur["pd_smooth"]),
            dpd=float(cur["dpd"]), utilisation=round(float(cur["utilisation"]), 3),
            inflow_vs_6m_avg=round(float(cur["inflow_vs_6m_avg"]), 3),
            sales_trend_3m=round(float(cur["sales_trend_3m"]), 3),
            reasons=reason_codes(Xte.iloc[pos], contribs[pos], cols),
            first_warning_lead=int(first_warn.get(acc_id, 0)),
            snap_months_to_npa=int(cur["months_to_npa"]),
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
        timelines[acc_id] = [dict(date=d, pd=round(float(p), 3), pd_smooth=round(float(ps), 3),
                                  utilisation=round(float(u), 3), inflow=int(round(inf)))
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

    out = dict(
        meta=dict(
            generated_from="synthetic MSME loan panel (6,000 accounts x 36 months); model=LightGBM",
            reference_month=str(snap["date"].iloc[0]), horizon_months=12, npa_definition_dpd=90,
            n_accounts_scored=int(port_df.account_id.nunique()),
        ),
        metrics=dict(
            auc=round(auc, 3), pr_auc=round(prauc, 3), ks=round(ks, 3),
            recall_at_budget=[dict(budget=b, recall=round(recall_at(b), 3)) for b in (0.02, 0.05, 0.10, 0.20)],
            recall_by_lead_time=lead_curve,
            median_first_warning_months=int(lead_series.median()),
            pct_flagged_6mo_ahead=round(float((lead_series >= 6).mean()), 3),
            rank_order=rank_order_exhibit(port_df),
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
    with open(OUT, "w") as f:
        json.dump(out, f)

    s = out["portfolio_summary"]
    print(f"AUC {auc:.3f} | KS {ks:.3f} | PR-AUC {prauc:.3f}  | ref month = {out['meta']['reference_month']}")
    print(f"book: {s['total_accounts']} accts  ->  RED {s['red']} / AMBER {s['amber']} / GREEN {s['green']}")
    print(f"exposure at risk (red): ₹{s['exposure_at_risk']:,.0f}")
    print(f"spotlight w/ timelines: {len(spotlight_ids)}  ({sum(1 for a in spotlight_ids if port_df.set_index('account_id').loc[a,'ground_truth_default']==1)} true future-defaults)")
    print(f"median first-warning lead: {out['metrics']['median_first_warning_months']} mo | >=6mo: {out['metrics']['pct_flagged_6mo_ahead']:.0%}")
    ro = out["metrics"]["rank_order"]
    print("rank-order 8m NPA rate: " + " | ".join(
        f"{b['band']} {b['bad_rate']:.1%} ({b['defaults']}/{b['n']})" for b in ro["by_band"]))
    print(f"recall@10% budget: {recall_at(0.10):.0%} | wrote {OUT} ({len(json.dumps(out))/1024:.0f} KB)")


if __name__ == "__main__":
    main()
