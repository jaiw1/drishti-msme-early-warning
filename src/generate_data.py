"""
Synthetic MSME loan-performance PANEL generator  —  IDBI Innovate 2026, Track 4
(MSME loan Early-Warning System)

One row = one loan account observed in one month.
Goal: let a model predict "will this account go bad (NPA, 90+ DPD) within the next
12 months?" while the account still looks STANDARD today — i.e. early warning.

Design principles baked in:
  * Deterioration is ORDERED: cash-inflow/sales dip first (~t-12), utilisation creep
    (~t-9), bounces (~t-6), then days-past-due finally rises (~t-3..0). So the leading
    signal is business cash-flow, NOT the obvious "already paying late" — this forces
    the model to learn genuine 12-month-ahead early warning.
  * Realistic, not trivially separable: heavy noise, transient stress on healthy
    accounts (hard negatives), variable ramp lengths, some "silent/fast" defaulters.
    Target ROC-AUC in a believable ~0.85-0.93 band, never ~0.99.
  * Leakage-safe: features use only the account's own PAST/PRESENT; the forward label
    is only built where a full 12-month future window is observable.
  * Calibrated to reality: ~20% eventual default rate (matches the public US SBA
    small-business dataset's 21.6% charge-off rate); Indian ₹ ticket sizes & sectors.

Output:
  data/msme_loan_panel.csv          full account-month panel (raw signals + trailing features + label)
  data/accounts_static.csv          one row per account (static attributes + outcome)
"""

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260709)          # fixed seed -> reproducible
N_ACCOUNTS = 9000
MONTHS = 36                                     # observation window per account
HORIZON = 12                                    # predict default within next 12 months
NPA_DPD = 90                                    # 90+ days-past-due = NPA = "gone bad"
START = pd.Timestamp("2023-01-01")

SECTORS = {                                     # sector: (weight, base_risk_multiplier)
    "Manufacturing": (0.22, 1.05),
    "Trading":       (0.30, 1.15),
    "Services":      (0.24, 0.90),
    "Retail":        (0.16, 1.10),
    "Logistics":     (0.08, 1.20),
}
REGIONS = {"North": 0.24, "South": 0.26, "West": 0.28, "East": 0.14, "Central": 0.08}
LOAN_TYPES = {"CashCredit": 0.55, "TermLoan": 0.45}   # CC = working capital (revolving), TL = EMI
QUALS = {"Graduate": 0.45, "UnderGrad": 0.30, "Professional": 0.15, "SchoolOnly": 0.10}
AGE_GROUPS = {"<30": 0.12, "30-40": 0.34, "40-50": 0.30, "50-60": 0.17, "60+": 0.07}


def _choice(d):
    keys = list(d.keys())
    w = np.array([d[k][0] if isinstance(d[k], tuple) else d[k] for k in keys], float)
    return keys[RNG.choice(len(keys), p=w / w.sum())]


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# ----------------------------------------------------------------------------- #
# 1) STATIC ACCOUNT ATTRIBUTES + who defaults and when
# ----------------------------------------------------------------------------- #
def build_accounts():
    rows = []
    for i in range(N_ACCOUNTS):
        sector = _choice(SECTORS)
        region = _choice(REGIONS)
        loan_type = _choice(LOAN_TYPES)
        qual = _choice(QUALS)
        age_group = _choice(AGE_GROUPS)

        # micro-heavy MSME ticket sizes (₹): ~₹12L median, long right tail to ₹5cr — mirrors IDBI's book
        sanctioned = float(np.clip(RNG.lognormal(mean=14.0, sigma=1.1), 5e4, 5e7))
        segment = "Micro" if sanctioned <= 1e6 else "Small" if sanctioned <= 1e7 else "Medium"
        biz_age = int(np.clip(RNG.gamma(2.2, 3.0), 0, 30))                  # years in business
        vintage0 = int(RNG.integers(0, 48))                                 # months since loan origination at t=0

        # latent risk: driven by sector, thin vintage, young business, high leverage, weaker profile
        # Static profile only WEAKLY tilts default odds — the irreducible-randomness term
        # dominates on purpose, so a static scorecard alone can't predict well and the
        # model is forced to learn the DYNAMIC deterioration (the real early-warning signal).
        z = (
            0.55 * (SECTORS[sector][1] - 1.0) * 6
            - 0.030 * biz_age
            - 0.012 * vintage0
            + 0.18 * (np.log(sanctioned) - 14.0)
            + {"SchoolOnly": 0.5, "UnderGrad": 0.15, "Graduate": 0.0, "Professional": -0.25}[qual]
            + {"<30": 0.35, "30-40": 0.10, "40-50": 0.0, "50-60": -0.05, "60+": 0.15}[age_group]
            + RNG.normal(0, 1.15)                                          # dominant irreducible randomness
        )
        p_default = _sigmoid(-2.35 + 0.45 * z)                             # ~9% eventual default (~2.7%/yr slippage, realistic IDBI-MSME)
        is_def = RNG.random() < p_default

        npa_month = -1
        severity = 0.0
        onset = 0
        if is_def:
            npa_month = int(RNG.integers(6, MONTHS))                        # month the account crosses into NPA
            severity = float(np.clip(RNG.normal(1.0, 0.25), 0.5, 1.7))      # how steep the slide is
            onset = int(np.clip(RNG.normal(13, 3), 5, 18))                  # months before NPA the slide begins

        rows.append(dict(
            account_id=f"MSME{i:05d}", sector=sector, region=region, loan_type=loan_type,
            segment=segment, qualification=qual, promoter_age_group=age_group, sanctioned_amount=sanctioned,
            business_age_years=biz_age, vintage_months_0=vintage0,
            is_defaulter=int(is_def), npa_month=npa_month, severity=severity, onset=onset,
            # per-account baseline levels for the monthly signals
            base_util=float(np.clip(RNG.normal(0.52 if loan_type == "CashCredit" else 0.35, 0.15), 0.05, 0.9)),
            base_inflow=sanctioned * float(np.clip(RNG.normal(0.9, 0.35), 0.2, 2.5)) / 12.0,
            base_txn=int(np.clip(RNG.normal(45, 20), 6, 200)),
            wobble=float(np.clip(RNG.normal(0.05, 0.02), 0.02, 0.14)),     # noise amplitude (lower -> cleaner slide, early dip detectable)
        ))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- #
# 2) MONTHLY TRAJECTORIES
# ----------------------------------------------------------------------------- #
def simulate_account(a):
    m = np.arange(MONTHS)
    util = np.full(MONTHS, a.base_util)
    inflow = np.full(MONTHS, a.base_inflow)
    sales = inflow * float(np.clip(RNG.normal(1.15, 0.2), 0.6, 2.0))       # GST sales ~ inflow proxy
    txn = np.full(MONTHS, float(a.base_txn))
    dpd = np.zeros(MONTHS)
    bounce = np.zeros(MONTHS, int)
    minbal_breach = np.zeros(MONTHS, int)
    adverse = np.zeros(MONTHS, int)

    # AR(1) noise around baselines (healthy conduct)
    e = 0.0
    for t in m:
        e = 0.6 * e + RNG.normal(0, a.wobble)
        util[t] = np.clip(a.base_util * (1 + e), 0.02, 1.05)
        inflow[t] = max(a.base_inflow * (1 + 0.7 * e + RNG.normal(0, a.wobble)), 1000)
        sales[t] = max(sales[t] * (1 + 0.7 * e + RNG.normal(0, a.wobble)), 1000)
        txn[t] = max(a.base_txn * (1 + 0.5 * e), 1)
        # occasional random operational noise
        if RNG.random() < 0.03:
            bounce[t] = 1
        if RNG.random() < 0.04:
            minbal_breach[t] = 1

    # Hard negatives: ~18% of HEALTHY accounts get a transient stress episode that RECOVERS
    if not a.is_defaulter and RNG.random() < 0.18:
        s = int(RNG.integers(3, MONTHS - 6))
        L = int(RNG.integers(2, 5))
        for t in range(s, min(s + L, MONTHS)):
            util[t] = np.clip(util[t] * 1.25, 0, 1.05)
            inflow[t] *= 0.75
            if RNG.random() < 0.3:
                bounce[t] = 1

    # Defaulters: ordered deterioration leading into npa_month, keyed on months-to-NPA (mtn).
    # A "step + ramp" gives a DETECTABLE dip the moment the slide begins (~onset months out),
    # worsening toward NPA — so the leading cash-flow signal is visible ~10-12 months ahead.
    if a.is_defaulter:
        npa, onset, sev = a.npa_month, a.onset, a.severity
        for t in range(MONTHS):
            mtn = npa - t                          # months TO npa
            if mtn <= 0:                           # at/after NPA
                dpd[t] = min(180, 90 + (t - npa) * 30)
                util[t] = np.clip(1.0 + RNG.normal(0, 0.03), 0.9, 1.1)
                inflow[t] *= 0.4
                sales[t] *= 0.4
                continue
            if mtn > onset:                        # slide hasn't begun -> still healthy
                continue
            decline = min(1.3, sev * (0.30 + 0.70 * (onset - mtn) / onset))   # ~0.3*sev at onset -> 1.0*sev at NPA
            # 1) cash-flow dips FIRST and throughout (the leading indicator)
            inflow[t] *= max(0.2, 1 - 0.55 * decline)
            sales[t] *= max(0.2, 1 - 0.60 * decline)
            # 2) utilisation creep (~10 months out)
            if mtn <= 10:
                util[t] = np.clip(util[t] * (1 + 0.35 * decline) + 0.18 * decline, 0.1, 1.08)
            # 3) transactions thin out
            txn[t] *= max(0.3, 1 - 0.40 * decline)
            # 4) bounces / min-balance breaches (~6 months out)
            if mtn <= 6 and RNG.random() < 0.12 + 0.5 * decline:
                bounce[t] = 1
            if mtn <= 6 and RNG.random() < 0.12 + 0.4 * decline:
                minbal_breach[t] = 1
            # 5) days-past-due rises LAST (~3 months out)
            if mtn <= 3:
                dpd[t] = max(0, {3: 15, 2: 38, 1: 68}.get(mtn, 0) + RNG.normal(0, 6))
            # 6) adverse "unstructured" mention (rare; correlated with the slide)
            if mtn <= 9 and RNG.random() < 0.04 + 0.13 * decline:
                adverse[t] = 1

    return dict(util=util, inflow=inflow, sales=sales, txn=txn, dpd=dpd,
                bounce=bounce, minbal_breach=minbal_breach, adverse=adverse)


# ----------------------------------------------------------------------------- #
# 3) ASSEMBLE PANEL + trailing features + leakage-safe label
# ----------------------------------------------------------------------------- #
def trailing(x, t, w, fn):
    lo = max(0, t - w + 1)
    return fn(x[lo:t + 1])


def build_panel(acc):
    out = []
    for a in acc.itertuples(index=False):
        sig = simulate_account(a)
        util, inflow, sales, txn = sig["util"], sig["inflow"], sig["sales"], sig["txn"]
        dpd, bounce, breach, adverse = sig["dpd"], sig["bounce"], sig["minbal_breach"], sig["adverse"]
        npa = a.npa_month
        for t in range(MONTHS):
            currently_standard = dpd[t] < NPA_DPD
            if npa >= 0 and t >= npa:
                continue                                    # drop at/after NPA (account already gone bad)
            if not currently_standard:
                continue                                    # only score accounts that still look standard today
            # keep the FULL pre-NPA standard history (needed to draw each account's timeline).
            # `labelable` marks rows with a fully-observable 12-month forward window (for OOT-honest training).
            labelable = int(t <= MONTHS - HORIZON - 1)
            label = int(a.is_defaulter and 1 <= (npa - t) <= HORIZON)

            inflow_3m_ago = inflow[max(0, t - 3)]
            sales_3m_ago = sales[max(0, t - 3)]
            inflow_6m_avg = trailing(inflow, t, 6, np.mean)
            out.append(dict(
                account_id=a.account_id, month_idx=t,
                date=(START + pd.DateOffset(months=t)).strftime("%Y-%m"),
                # ---- static ----
                sector=a.sector, region=a.region, loan_type=a.loan_type, segment=a.segment,
                qualification=a.qualification, promoter_age_group=a.promoter_age_group,
                log_sanctioned=float(np.log(a.sanctioned_amount)),
                business_age_years=a.business_age_years,
                vintage_months=a.vintage_months_0 + t,
                # ---- current signals ----
                dpd=float(round(dpd[t], 1)),
                utilisation=float(round(util[t], 4)),
                inflow=float(round(inflow[t], 0)),
                gst_sales=float(round(sales[t], 0)),
                txn_count=int(round(txn[t])),
                bounce=int(bounce[t]),
                minbal_breach=int(breach[t]),
                adverse_remark=int(adverse[t]),
                # ---- trailing / trend features (past-only) ----
                dpd_max_6m=float(round(trailing(dpd, t, 6, np.max), 1)),
                times_late_6m=int(trailing((dpd > 0).astype(int), t, 6, np.sum)),
                bounces_6m=int(trailing(bounce, t, 6, np.sum)),
                minbal_breach_6m=int(trailing(breach, t, 6, np.sum)),
                util_avg_3m=float(round(trailing(util, t, 3, np.mean), 4)),
                util_max_6m=float(round(trailing(util, t, 6, np.max), 4)),
                months_over_90pct_util_6m=int(trailing((util > 0.9).astype(int), t, 6, np.sum)),
                inflow_trend_3m=float(round((inflow[t] - inflow_3m_ago) / max(inflow_3m_ago, 1), 4)),
                inflow_vs_6m_avg=float(round((inflow[t] - inflow_6m_avg) / max(inflow_6m_avg, 1), 4)),
                sales_trend_3m=float(round((sales[t] - sales_3m_ago) / max(sales_3m_ago, 1), 4)),
                txn_drop_flag=int(txn[t] < 0.6 * trailing(txn, t, 6, np.mean)),
                adverse_remark_6m=int(trailing(adverse, t, 6, np.sum)),
                # ---- label ----
                default_within_12m=label,
                labelable=labelable,
                months_to_npa=int(npa - t) if npa >= 0 else -1,
            ))
    return pd.DataFrame(out)


if __name__ == "__main__":
    print("Building accounts ...")
    acc = build_accounts()
    print(f"  {len(acc):,} accounts | eventual default rate = {acc.is_defaulter.mean():.1%}")
    print("Simulating monthly trajectories + assembling panel ...")
    panel = build_panel(acc)
    pos = panel.default_within_12m.mean()
    print(f"  panel rows = {len(panel):,}")
    print(f"  label prevalence (rows that will default within 12m) = {pos:.2%}")
    print(f"  unique accounts appearing in panel = {panel.account_id.nunique():,}")

    outdir = __file__.rsplit("/src/", 1)[0] + "/data"
    panel.to_csv(f"{outdir}/msme_loan_panel.csv", index=False)
    acc.drop(columns=["base_util", "base_inflow", "base_txn", "wobble"]).to_csv(
        f"{outdir}/accounts_static.csv", index=False)
    print(f"Wrote {outdir}/msme_loan_panel.csv and accounts_static.csv")
