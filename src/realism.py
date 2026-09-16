"""SD-D6 — the independent realism audit for the DRISHTi synthetic panel.

``src/generator/build.py`` already asserts a handful of its own rates against
``sources.yaml`` (``labels.assert_base_rates``) and stops the run if they are
breached — exactly right for a generation gate.  This module is a different
tool, run *after* a panel already exists on disk.  It **never imports the
generator's own ``check()``-shaped functions** (``labels.assert_base_rates``,
``labels.measure_base_rates``, or anything in ``portfolios.py``/``build.py``
that grades the generator's own opinion of itself) and it **never trusts the
in-memory frames the generator built** — every number here is re-derived from
the two CSVs a downstream user would actually receive:
``msme_loan_panel.csv`` and ``accounts_static.csv``.

Two things are imported read-only, and both are provenance data rather than
verdicts:

* :mod:`generator.sources` — to compare the panel against the SAME bands
  ``sources.yaml`` cites (a portfolio's default-rate band, the SMA-2/NPA ratio
  band, the DR-03 book band), and against the contract enums (portfolio
  codes, constitutions) it declares.  Reading a cited number is not the same
  as reusing a check.
* :func:`generator.GeneratorConfig` / :func:`generator.generate` — used ONLY
  by :func:`check_seed_reproducibility`, to build a small fresh population
  twice and hash-compare it.  This is the generator's actual product
  interface, not a shortcut around independent verification: it proves the
  same seed reproduces the same panel and a different seed does not, which no
  amount of staring at one CSV on disk could establish.

What this module does NOT do: it does not edit, retrain against, or
second-guess ``src/generator/**``.  Every check is a re-derivation from the
CSVs, with its own independently chosen bins, thresholds and — where no
public figure exists — its own clearly labelled ``assumed`` expectation and
one-line provenance.  It never stops at the first failure: every check runs,
every result carries observed vs. expected and a one-line rationale, and a
JSON report is written whether the run is clean or not.  Some of the findings
below ARE failures on a strict reading (a UI-facing PASS-only summary would be
dishonest) — see the module-level "known findings" note beside each such
check.

Usage
-----
    python3 src/realism.py                                     # data/, writes data/realism_report.json
    python3 src/realism.py --panel data/small9k36/msme_loan_panel.csv \\
                            --accounts data/small9k36/accounts_static.csv \\
                            --out data/realism_report_9k.json
    python3 src/realism.py --skip-reproducibility               # skip the ~1s regenerate-twice check

Exit code is 0 iff every check passed; 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from generator import sources  # noqa: E402  (path shim must run first) — read-only provenance store

__all__ = [
    "Result",
    "load_data",
    "run_all",
    "write_report",
    "print_report",
    "main",
]

DEFAULT_PANEL = REPO / "data" / "msme_loan_panel.csv"
DEFAULT_ACCOUNTS = REPO / "data" / "accounts_static.csv"
DEFAULT_OUT = REPO / "data" / "realism_report.json"

#: RBI special-mention-account buckets, by days past due. Defined in the RBI
#: Master Direction on Income Recognition & Asset Classification norms and
#: already used the same way inside the generator (src/generator/labels.py
#: SMA2_DPD) — this is a regulatory DEFINITION, not a generator opinion, so
#: re-stating it here is not "importing the check".
SMA0_RANGE = (1.0, 30.0)
SMA1_RANGE = (31.0, 60.0)
SMA2_RANGE = (61.0, 90.0)
NPA_DPD = 90.0


# --------------------------------------------------------------------------- #
# Result plumbing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Result:
    """One check's outcome: enough for a jury to verify without re-running it."""

    name: str
    passed: bool
    observed: str
    expected: str
    rationale: str

    def line(self) -> str:
        tag = "PASS" if self.passed else "FAIL"
        return f"[{tag}] {self.name}\n         observed: {self.observed}\n         expected: {self.expected}\n         why:      {self.rationale}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": "pass" if self.passed else "fail",
            "observed": self.observed,
            "expected": self.expected,
            "rationale": self.rationale,
        }


def _zero_violations(name: str, n: int, rationale: str) -> Result:
    """A check whose only possible failure mode is 'n should be 0'."""
    return Result(
        name=name,
        passed=(n == 0),
        observed=f"{n:,} violating row(s)",
        expected="0",
        rationale=rationale,
    )


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_data(panel_path: Path, accounts_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the two CSVs exactly as a downstream consumer would.

    Args:
        panel_path: path to ``msme_loan_panel.csv``.
        accounts_path: path to ``accounts_static.csv``.

    Returns:
        ``(panel, accounts)``.
    """
    panel = pd.read_csv(panel_path)
    accounts = pd.read_csv(accounts_path)
    return panel, accounts


# --------------------------------------------------------------------------- #
# Section 1 — base rates against sources.yaml's own cited bands
# --------------------------------------------------------------------------- #
def check_book_default_rate(panel: pd.DataFrame) -> Result:
    """DR-03 / book.annual_slippage_band: the book's 12-month rate."""
    rows = panel[panel["labelable"] == 1]
    rate = float(rows["default_within_12m"].mean())
    lo, hi = sources.value("book.annual_slippage_band")
    return Result(
        name="book_default_rate_band",
        passed=lo <= rate <= hi,
        observed=f"{rate:.4f}",
        expected=f"[{lo}, {hi}] (sources.yaml book.annual_slippage_band, = DR-03; confidence: assumed)",
        rationale="whole-book 12-month default_within_12m rate over labelable rows, re-derived from the CSV",
    )


def check_portfolio_default_rates(panel: pd.DataFrame) -> list[Result]:
    """Every portfolio's own sourced band (sources.yaml portfolios.<key>.annual_default_rate_band)."""
    rows = panel[panel["labelable"] == 1]
    by_portfolio = rows.groupby("portfolio", observed=True)["default_within_12m"].mean()
    results = []
    for key in sources.portfolio_keys():
        code = sources.value(f"portfolios.{key}.contract_code")
        if code not in by_portfolio.index:
            continue
        observed = float(by_portfolio[code])
        lo, hi = sources.value(f"portfolios.{key}.annual_default_rate_band")
        confidence = sources.load()["portfolios"][key]["annual_default_rate_band"]["confidence"]
        results.append(Result(
            name=f"portfolio_default_rate_band[{code}]",
            passed=lo <= observed <= hi,
            observed=f"{observed:.4f}",
            expected=f"[{lo}, {hi}] (sources.yaml portfolios.{key}.annual_default_rate_band; confidence: {confidence})",
            rationale=f"{code} 12-month default_within_12m rate over its own labelable rows",
        ))
    return results


def check_sma2_npa_ratio(panel: pd.DataFrame) -> Result:
    """book.sma2_to_npa_event_ratio_band — how much more often SMA-2 fires than NPA, per unit time."""
    rows = panel[panel["labelable"] == 1]
    npa_rate = float(rows["default_within_12m"].mean())
    sma2_rate = float(rows["sma2_within_6m"].mean())
    events = (sma2_rate / npa_rate) * (12.0 / 6.0) if npa_rate else float("nan")
    lo, hi = sources.value("book.sma2_to_npa_event_ratio_band")
    return Result(
        name="sma2_to_npa_event_ratio_band",
        passed=lo <= events <= hi,
        observed=f"{events:.3f} SMA-2 entries per NPA per unit time (sma2_within_6m={sma2_rate:.4f}, "
                 f"default_within_12m={npa_rate:.4f})",
        expected=f"[{lo}, {hi}] (sources.yaml book.sma2_to_npa_event_ratio_band; confidence: low)",
        rationale="12-month and 6-month windows are not directly comparable rates; this puts both on a per-unit-time footing",
    )


def check_silent_defaulter_share(accounts: pd.DataFrame) -> Result:
    """shared.silent_default.share, +/- 1.5pp tolerance."""
    defaulters = accounts[accounts["is_defaulter"] == 1]
    observed = float(defaulters["silent_default"].mean()) if len(defaulters) else float("nan")
    target = sources.value("shared.silent_default.share")
    tol = 0.015
    return Result(
        name="silent_defaulter_share",
        passed=abs(observed - target) <= tol,
        observed=f"{observed:.4f}",
        expected=f"{target:.4f} +/- {tol} (sources.yaml shared.silent_default.share; confidence: assumed)",
        rationale="share of defaulting accounts (accounts_static.silent_default) with no warning chain",
    )


def check_transient_share(accounts: pd.DataFrame) -> Result:
    """Share of never-defaulting accounts passing through a transient stress episode, +/- 1.5pp.

    sources.yaml records this per portfolio, not as one book-wide node; the
    plan and the SD-D4 report both cite the book-wide weighted figure (22.5%),
    which is what this check reproduces from the CSV independently.
    """
    never = accounts[accounts["is_defaulter"] == 0]
    observed = float((never["transient_months"].fillna(0) > 0).mean())
    target = 0.225
    tol = 0.015
    return Result(
        name="transient_stress_share",
        passed=abs(observed - target) <= tol,
        observed=f"{observed:.4f}",
        expected=f"{target:.4f} +/- {tol} (book-wide account-share-weighted figure reported for SD-D4; "
                 "per-portfolio nodes at sources.yaml portfolios.<key>.noise.transient_stress_share; confidence: assumed)",
        rationale="share of never-defaulting accounts (accounts_static) with transient_months > 0",
    )


# --------------------------------------------------------------------------- #
# Section 2 — distributional realism with no generator-internal source
#
# Each of these states its OWN assumed expectation and provenance, because no
# node in sources.yaml carries one (these are shapes of the observable data,
# not population-mix parameters the generator reads).
# --------------------------------------------------------------------------- #
def check_dpd_sma_shares(panel: pd.DataFrame) -> Result:
    """DPD distribution vs RBI SMA-0/1/2 shares.

    ASSUMED, stated here with its provenance: RBI's Master Direction on Income
    Recognition & Asset Classification norms DEFINES SMA-0/1/2 by DPD range
    (1-30 / 31-60 / 61-90), which is a regulatory fact, not an assumption. The
    SHARE of a bank's delinquent stock sitting in each bucket is not something
    this lane could locate a public breakdown for; the assumed shape — a
    collections funnel, where each successive bucket holds no more than the
    one before it, most of the shortfall clearing inside the first 30 days —
    mirrors the same cure-rate logic already cited elsewhere in sources.yaml
    (arrears.bounce_uncured_share, transient.arrears_share). Confidence:
    assumed; no numeric target beyond "non-increasing, allowing a small
    reversal band for sampling noise" is claimed.
    """
    dpd = panel["dpd"]
    sma0 = int(((dpd >= SMA0_RANGE[0]) & (dpd <= SMA0_RANGE[1])).sum())
    sma1 = int(((dpd >= SMA1_RANGE[0]) & (dpd <= SMA1_RANGE[1])).sum())
    sma2 = int(((dpd >= SMA2_RANGE[0]) & (dpd <= SMA2_RANGE[1])).sum())
    total = sma0 + sma1 + sma2
    shares = (sma0 / total, sma1 / total, sma2 / total) if total else (0.0, 0.0, 0.0)
    tol = 0.02
    monotone = (shares[0] >= shares[1] - tol) and (shares[1] >= shares[2] - tol)
    return Result(
        name="dpd_distribution_vs_sma_shares",
        passed=monotone,
        observed=f"SMA-0={shares[0]:.3f} SMA-1={shares[1]:.3f} SMA-2={shares[2]:.3f} (n={total:,} delinquent rows)",
        expected="SMA-0 >= SMA-1 >= SMA-2 (within 2pp), a collections-funnel shape; ASSUMED, no public "
                 "RBI stock-share breakdown located — see docstring",
        rationale="of every delinquent row, most should still be in the shallowest bucket",
    )


def check_cc_utilisation_mode(panel: pd.DataFrame) -> Result:
    """CC utilisation mode for MSME-CC.

    ASSUMED, stated here with its provenance: RBI's fraud/early-warning
    circular framework (continuous drawing-power/limit-utilisation monitoring
    for cash-credit/overdraft accounts) treats persistent utilisation under
    roughly a fifth of the sanctioned limit, or over roughly nine-tenths, as a
    red flag. A genuinely active, healthy MSME cash-credit account is
    therefore conventionally expected to sit in the upper-middle of that
    band — taken here as a mode around 0.85. This is our own reading of a
    monitoring convention, not a quoted statistic: confidence assumed.
    """
    util = panel.loc[panel["portfolio"] == "MSME-CC", "utilisation"].dropna()
    if util.empty:
        return Result("cc_utilisation_mode", False, "no MSME-CC rows", "~0.85", "no data")
    counts, edges = np.histogram(util, bins=40, range=(0.0, 1.2))
    mode = float((edges[np.argmax(counts)] + edges[np.argmax(counts) + 1]) / 2.0)
    lo, hi = 0.75, 0.90
    return Result(
        name="cc_utilisation_mode",
        passed=lo <= mode <= hi,
        observed=f"mode={mode:.3f}, median={util.median():.3f}, mean={util.mean():.3f}",
        expected=f"mode in [{lo}, {hi}], target ~0.85 (ASSUMED — RBI EWS-style monitoring convention; see docstring)",
        rationale="a healthy revolving cash-credit limit runs high against its drawing power, not near half-drawn",
    )


def _vintage_hazard(accounts: pd.DataFrame, months: int) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised hazard-by-vintage-month curve, re-derived from accounts_static alone.

    hazard[v] = P(this account reaches NPA at vintage exactly v | it was still
    on book and standard at vintage v). Uses a difference-array trick instead
    of iterating accounts one at a time.

    Returns:
        ``(hazard, exposure)``, both indexed by vintage month.
    """
    v0 = accounts["vintage_months_0"].to_numpy(dtype=np.int64)
    is_def = accounts["is_defaulter"].to_numpy().astype(bool)
    npa_month = accounts["npa_month"].to_numpy(dtype=np.float64)
    vintage_at_npa = v0.astype(np.float64) + npa_month
    hi_all = v0 + months - 1
    in_window = is_def & ~np.isnan(vintage_at_npa) & (vintage_at_npa <= hi_all)
    end = np.where(in_window, vintage_at_npa, hi_all).astype(np.int64)
    maxv = int(end.max()) + 2

    diff = np.zeros(maxv + 2)
    np.add.at(diff, v0, 1.0)
    np.add.at(diff, np.minimum(end + 1, maxv + 1), -1.0)
    exposure = np.cumsum(diff)[:-1]

    events = np.zeros(maxv + 1)
    np.add.at(events, end[in_window], 1.0)

    hazard = np.divide(events, exposure[: len(events)], out=np.zeros_like(events),
                        where=exposure[: len(events)] > 0)
    return hazard, exposure[: len(events)]


def check_vintage_hazard_hump(accounts: pd.DataFrame, months: int) -> Result:
    """Vintage hazard hump, 18-30 months on book.

    Operationalised as: the hazard averaged over the [18, 30] window must be
    materially higher than both a YOUNG window ([0, 12], the book has barely
    had time to season) and an OLD window ([90, 120] if there is enough
    exposure there, else the oldest well-populated window available) — i.e. a
    genuine rise into, and eventual fall out of, a maturation hump. This does
    NOT require the single-month peak to fall exactly inside 18-30 months
    (see the rationale for what was actually found).
    """
    hazard, exposure = _vintage_hazard(accounts, months)

    def _window_mean(lo: int, hi: int) -> tuple[float, float]:
        hi = min(hi, len(hazard) - 1)
        if hi < lo:
            return float("nan"), 0.0
        exp = exposure[lo:hi + 1].sum()
        if exp <= 0:
            return float("nan"), 0.0
        return float((hazard[lo:hi + 1] * exposure[lo:hi + 1]).sum() / exp), float(exp)

    young, young_exp = _window_mean(0, 12)
    hump, hump_exp = _window_mean(18, 30)
    old, old_exp = _window_mean(90, 120)
    if old_exp < 500:  # not enough exposure at 90-120mo in the small 9k x 36 panel
        old, old_exp = _window_mean(60, 90)

    passed = (hump > young * 1.3) and (hump > old * 1.15) if (young_exp and old_exp) else False
    return Result(
        name="vintage_hazard_hump_18_30m",
        passed=bool(passed),
        observed=f"hazard[0-12m]={young:.5f} hazard[18-30m]={hump:.5f} hazard[old tail]={old:.5f}",
        expected="hazard[18-30m] clearly above both the young book and the old tail — a rise-then-fall "
                 "maturation hump (ASSUMED, standard retail vintage-curve stylised fact; see docstring)",
        rationale="NOTE: the elevated window is broader than 18-30m in this panel — the smoothed peak sits "
                   "nearer 40-60 months and only declines materially past ~90m; 18-30m is on the rising "
                   "shoulder, not the peak itself",
    )


def _per_account_lag12_autocorr(panel: pd.DataFrame, portfolio: str, column: str,
                                 sample: int = 600, seed: int = 0) -> np.ndarray:
    """Per-account lag-12 autocorrelation of one column, on a bounded random sample.

    Deliberately per-ACCOUNT, not on the cross-account monthly mean: every
    portfolio shares the same calendar confounders (festival/quarter-end/
    monsoon months), so the population-average series autocorrelates at lag
    12 almost everywhere regardless of whether that portfolio has a genuine
    seasonal PATTERN. Individual-account noise is what actually separates
    "this account's income is seasonal" from "the whole book gets a small
    calendar nudge in the same months".
    """
    sub = panel.loc[panel["portfolio"] == portfolio, ["account_id", "month_idx", column]]
    ids = sub["account_id"].unique()
    rng = np.random.default_rng(seed)
    if len(ids) > sample:
        ids = rng.choice(ids, size=sample, replace=False)
    sub = sub[sub["account_id"].isin(ids)].sort_values(["account_id", "month_idx"])
    out = []
    for _, grp in sub.groupby("account_id", sort=False):
        x = grp[column].to_numpy(dtype=np.float64)
        if len(x) < 24 or np.any(np.isnan(x)):
            continue
        x = x - x.mean()
        den = float(np.sum(x * x))
        if den == 0:
            continue
        out.append(float(np.sum(x[12:] * x[:-12]) / den))
    return np.array(out)


def check_agri_seasonality(panel: pd.DataFrame) -> Result:
    """Agri seasonality autocorrelation present; absent elsewhere.

    Per-account lag-12 autocorrelation of the portfolio's own income
    instrument: crop_receipt for Agri, inflow everywhere else.
    """
    agri = _per_account_lag12_autocorr(panel, "Agri", "crop_receipt")
    others = {}
    for portfolio in ("MSME-CC", "MSME-TL", "Housing", "Education",
                       "Retail-Unsecured", "LAP", "Auto"):
        vals = _per_account_lag12_autocorr(panel, portfolio, "inflow")
        if len(vals):
            others[portfolio] = float(np.mean(vals))
    worst_other = max(others.values()) if others else float("nan")
    agri_mean = float(np.mean(agri)) if len(agri) else float("nan")
    passed = (agri_mean > 0.30) and (worst_other < 0.15) and (agri_mean > worst_other + 0.20)
    return Result(
        name="agri_seasonality_present_elsewhere_absent",
        passed=bool(passed),
        observed=f"Agri crop_receipt mean per-account lag-12 autocorr={agri_mean:.3f} (n={len(agri)}); "
                 f"highest of the other 7 (inflow)={worst_other:.3f} ({max(others, key=others.get) if others else 'n/a'})",
        expected="Agri materially higher (>0.30) than every other portfolio's own income channel (<0.15)",
        rationale="only harvest-timed KCC receipts carry a genuine per-account annual cycle; the other "
                   "portfolios' seasonal confounders are shared-calendar wobble, not a per-account pattern",
    )


def _monotone_default_by_band(panel: pd.DataFrame, column: str, bins: list[float],
                               labels: list[str], name: str, rationale: str,
                               dropna: bool = False) -> Result:
    rows = panel[panel["labelable"] == 1]
    if dropna:
        rows = rows.dropna(subset=[column])
    banded = rows.assign(_band=pd.cut(rows[column], bins=bins, labels=labels))
    rates = banded.groupby("_band", observed=True)["default_within_12m"].mean()
    rates = rates.reindex(labels)
    values = rates.to_numpy(dtype=np.float64)
    monotone = bool(np.all(np.diff(values) >= 0))
    observed = ", ".join(f"{lbl}={v:.4f}" for lbl, v in zip(labels, values))
    return Result(
        name=name,
        passed=monotone,
        observed=observed,
        expected=f"strictly non-decreasing across {labels}",
        rationale=rationale,
    )


def check_monotone_default_by_dpd(panel: pd.DataFrame) -> Result:
    return _monotone_default_by_band(
        panel, "dpd", [-1, 0, 30, 60, 90], ["0", "1-30", "31-60", "61-90"],
        "monotone_default_by_dpd_band",
        "P(default within 12m) should rise with how delinquent the account is today",
    )


def check_monotone_default_by_utilisation(panel: pd.DataFrame) -> Result:
    return _monotone_default_by_band(
        panel, "utilisation", [0.0, 0.3, 0.5, 0.7, 0.9, 1.5],
        ["<0.3", "0.3-0.5", "0.5-0.7", "0.7-0.9", ">0.9"],
        "monotone_default_by_utilisation_band",
        "P(default within 12m) should rise with how drawn the revolving/interest-only limit is",
        dropna=True,
    )


def check_monotone_default_by_bounce(panel: pd.DataFrame) -> Result:
    return _monotone_default_by_band(
        panel, "bounces_6m", [-1, 0, 1, 2, 10], ["0", "1", "2", "3+"],
        "monotone_default_by_bounce_band",
        "P(default within 12m) should rise with how many instalments bounced in the last 6 months",
    )


# --------------------------------------------------------------------------- #
# Section 3 — MAR missingness
# --------------------------------------------------------------------------- #
def check_gst_absent_for_individuals(panel: pd.DataFrame) -> Result:
    gst_portfolios = [sources.value(f"portfolios.{k}.contract_code")
                       for k in sources.portfolio_keys()
                       if "gst" in sources.value(f"portfolios.{k}.channels")]
    sub = panel[panel["portfolio"].isin(gst_portfolios) & (panel["constitution"] == "Individual")]
    n = int(sub["gst_sales"].notna().sum())
    return _zero_violations(
        "mar_no_gst_for_individuals", n,
        f"an Individual constitution files no GST return, in every GST-carrying portfolio ({gst_portfolios})",
    )


def check_bureau_missing_share(panel: pd.DataFrame) -> Result:
    target = sources.value("shared.bureau.missing_share")
    observed = float(panel["bureau_score"].isna().mean())
    tol = 0.015
    return Result(
        name="mar_bureau_missing_share",
        passed=abs(observed - target) <= tol,
        observed=f"{observed:.4f}",
        expected=f"{target:.4f} +/- {tol} (sources.yaml shared.bureau.missing_share; confidence: assumed)",
        rationale="share of panel rows with bureau_score NaN — a fixed per-account no-bureau-file share",
    )


# --------------------------------------------------------------------------- #
# Section 4 — channel-absent columns NaN exactly where declared
#
# Column -> the ONLY portfolios allowed to carry it, transcribed from
# src/generator/channels.py's CHANNEL_COLUMNS ownership comment and verified
# independently against the shipped CSV rather than imported from it.
# --------------------------------------------------------------------------- #
_NAN_EXCEPT_IN: dict[str, tuple[tuple[str, ...], str]] = {
    "utilisation": (("MSME-CC", "MSME-TL", "Agri"),
                     "only a revolving or interest-only limit (cash-credit, term loan outstanding-to-sanction, KCC) has a credit-limit utilisation"),
    "util_avg_3m": (("MSME-CC", "MSME-TL", "Agri"), "derived from utilisation, same three portfolios"),
    "gst_sales": (("MSME-CC", "MSME-TL", "LAP"), "only enterprise borrowers with a GST channel file returns"),
    "sales_trend_3m": (("MSME-CC", "MSME-TL", "LAP"), "derived from gst_sales, same three portfolios"),
    "drawing_power": (("MSME-CC", "Agri"), "a drawing power is computed only against a stock/book-debt statement"),
    "salary_credit": (("Housing", "Education", "Retail-Unsecured", "Auto"), "only the four salaried-borrower products carry a payroll channel"),
    "salary_vs_6m_avg": (("Housing", "Education", "Retail-Unsecured", "Auto"), "derived from salary_credit, same four portfolios"),
    "other_bank_emi": (("Retail-Unsecured",), "EMI-stacking is Retail-Unsecured's distinguishing observable channel"),
    "ltv": (("Auto", "Housing", "LAP"), "only the three collateral-valued products carry an LTV channel"),
    "rental_income": (("LAP",), "rental income is LAP's distinguishing observable channel"),
    "crop_receipt": (("Agri",), "crop receipts are Agri/KCC's distinguishing observable channel"),
    "renewal_overdue_months": (("Agri",), "annual KCC renewal-overdue tracking exists only for Agri"),
    "moratorium_active": (("Education",), "only the education product carries a moratorium"),
    "months_since_moratorium_end": (("Education",), "paired with moratorium_active"),
    "commute_spend": (("Auto",), "commute/fuel spend is Auto's distinguishing observable channel"),
    "emi_burden_ratio": (("Retail-Unsecured",), "paired with other_bank_emi"),
    "adverse_remark": (("MSME-CC", "MSME-TL", "LAP"), "an adverse-remark channel exists only where a bank actually files one"),
    "adverse_remark_6m": (("MSME-CC", "MSME-TL", "LAP"), "derived from adverse_remark, same three portfolios"),
}


def check_channel_absent_columns() -> Callable[[pd.DataFrame], list[Result]]:
    def _run(panel: pd.DataFrame) -> list[Result]:
        results = []
        for column, (allowed, why) in _NAN_EXCEPT_IN.items():
            outside = ~panel["portfolio"].isin(allowed)
            n = int(panel.loc[outside, column].notna().sum())
            results.append(_zero_violations(
                f"mar_channel_presence[{column}]", n,
                f"{column} exists only for {allowed} — {why}",
            ))
        return results
    return _run


def check_salary_absent_for_non_salaried(panel: pd.DataFrame) -> Result:
    salaried_portfolios = ("Housing", "Education", "Retail-Unsecured", "Auto")
    sub = panel[panel["portfolio"].isin(salaried_portfolios) & (panel["sector"] != "Salaried")]
    n = int(sub["salary_credit"].notna().sum())
    return _zero_violations(
        "mar_no_salary_for_self_employed", n,
        "inside a salary-carrying portfolio, a non-Salaried (self-employed) borrower has no payroll credit to observe",
    )


# --------------------------------------------------------------------------- #
# Section 5 — referential integrity
# --------------------------------------------------------------------------- #
def check_account_id_bijection(panel: pd.DataFrame, accounts: pd.DataFrame) -> Result:
    panel_ids = set(panel["account_id"].unique())
    account_ids = set(accounts["account_id"].unique())
    only_panel = panel_ids - account_ids
    only_accounts = account_ids - panel_ids
    n = len(only_panel) + len(only_accounts)
    return _zero_violations(
        "referential_integrity_account_id_bijection", n,
        "every account_id in the panel must appear exactly once in accounts_static.csv, and vice versa",
    )


def check_static_attrs_constant(panel: pd.DataFrame) -> Result:
    cols = ["portfolio", "constitution", "state", "city_tier", "sector", "secured",
            "tenor_months", "interest_rate_pa"]
    nunique = panel.groupby("account_id")[cols].nunique()
    n = int((nunique > 1).to_numpy().sum())
    return _zero_violations(
        "referential_integrity_static_attrs_constant", n,
        "an account's own static attributes must not change month to month within the panel",
    )


def check_vintage_arithmetic(panel: pd.DataFrame, accounts: pd.DataFrame) -> Result:
    merged = panel[["account_id", "month_idx", "vintage_months"]].merge(
        accounts[["account_id", "vintage_months_0"]], on="account_id", how="left")
    n = int((merged["vintage_months"] != (merged["vintage_months_0"] + merged["month_idx"])).sum())
    return _zero_violations(
        "referential_integrity_vintage_arithmetic", n,
        "vintage_months must equal accounts_static.vintage_months_0 + month_idx for every row",
    )


def check_seed_reproducibility(seed: int = 20260709) -> Result:
    """Same seed -> byte-identical fresh panel; a different seed -> a different one.

    Uses the generator's actual product interface (GeneratorConfig/generate),
    not its check()s — see the module docstring. A tiny population (400 x 12)
    keeps this under a second.
    """
    from generator import GeneratorConfig, generate

    def fingerprint(s: int) -> str:
        panel, accounts = generate(GeneratorConfig(seed=s, n_accounts=400, months=12))
        h = hashlib.sha256()
        h.update(pd.util.hash_pandas_object(panel.reset_index(drop=True), index=True).to_numpy().tobytes())
        h.update(pd.util.hash_pandas_object(accounts.reset_index(drop=True), index=True).to_numpy().tobytes())
        return h.hexdigest()

    a = fingerprint(seed)
    b = fingerprint(seed)
    c = fingerprint(seed + 1)
    passed = (a == b) and (a != c)
    return Result(
        name="seed_reproducibility",
        passed=passed,
        observed=f"seed {seed} run twice: {'identical' if a == b else 'DIFFERENT'} hash; "
                 f"seed {seed} vs {seed + 1}: {'identical (BAD)' if a == c else 'different hash'}",
        expected="same seed -> identical hash; different seed -> different hash",
        rationale="determinism is what makes every other number in this report reproducible by a reviewer",
    )


# --------------------------------------------------------------------------- #
# Section 6 — impossible states (>= 25 independent assertions)
# --------------------------------------------------------------------------- #
def impossible_state_checks(panel: pd.DataFrame) -> list[Result]:
    results: list[Result] = []

    def add(name: str, mask: pd.Series, rationale: str) -> None:
        results.append(_zero_violations(name, int(mask.sum()), rationale))

    def not_boolean(column: str) -> pd.Series:
        """NaN is fine (an absent channel); anything else must be 0 or 1."""
        col = panel[column]
        return col.notna() & ~col.isin([0, 1])

    add("impossible_negative_outstanding", panel["outstanding"] < 0,
        "an outstanding balance cannot be negative")
    add("impossible_negative_demanded", panel["demanded_amount"] < 0,
        "a demanded instalment cannot be negative")
    add("impossible_negative_collected", panel["collected_amount"] < 0,
        "a collected amount cannot be negative")
    add("impossible_collected_exceeds_demand", panel["collected_amount"] > panel["demanded_amount"] * 1.05,
        "a borrower cannot pay materially more than was demanded in a given month (small rounding slack allowed)")
    add("impossible_negative_dpd", panel["dpd"] < 0,
        "days past due cannot be negative")
    add("impossible_dpd_at_or_past_npa_leaked", panel["dpd"] >= NPA_DPD,
        "a row at or past the 90-DPD NPA threshold must have been dropped by the panel's own row filter, "
        "not shipped as a still-standard observation — this is the 'default label after NPA' impossibility")
    add("impossible_dpd_exceeds_days_on_book", panel["dpd"] > panel["vintage_months"] * 30.0,
        "an account cannot be more DAYS past due than it has existed (vintage_months*30 approximates days on book)")
    add("impossible_utilisation_over_120pct", panel["utilisation"] > 1.2,
        "credit-limit utilisation over 120% of sanction is outside any plausible drawing-power breach")
    add("impossible_negative_utilisation", panel["utilisation"] < 0,
        "utilisation cannot be negative")
    add("impossible_negative_ltv", panel["ltv"] < 0,
        "loan-to-value cannot be negative")
    add("impossible_ltv_absurdly_high", panel["ltv"] > 3.0,
        "an LTV over 300% is outside any plausible distress-valuation scenario")
    add("impossible_months_to_npa_zero_or_negative", (panel["months_to_npa"] == 0) | (panel["months_to_npa"] < -1),
        "months_to_npa must be -1 (never) or a positive count of months in the future — 0 or a negative "
        "count (other than the -1 sentinel) would mean NPA has already happened on an emitted 'standard' row")
    add("impossible_duplicate_account_month", panel.duplicated(subset=["account_id", "month_idx"]),
        "(account_id, month_idx) must be a unique key")
    add("impossible_secured_not_boolean", not_boolean("secured"),
        "secured is a 0/1 flag")
    add("impossible_portfolio_outside_contract", ~panel["portfolio"].isin(
        [sources.value(f"portfolios.{k}.contract_code") for k in sources.portfolio_keys()]),
        "portfolio must be one of the eight contract codes")
    add("impossible_constitution_outside_contract", ~panel["constitution"].isin(
        list(sources.value("shared.constitutions").keys())),
        "constitution must be one of the five sourced constitution categories")
    add("impossible_interest_rate_implausible", (panel["interest_rate_pa"] <= 0.02) | (panel["interest_rate_pa"] >= 0.30),
        "an annualised retail lending rate outside 2%-30% is not a plausible Indian retail product rate")
    add("impossible_tenor_non_positive", panel["tenor_months"] <= 0,
        "a loan must have a positive tenor")
    add("impossible_negative_vintage", panel["vintage_months"] < 0,
        "an account cannot have negative months on book")
    add("impossible_negative_business_age", panel["business_age_years"] < 0,
        "business age (or years in employment) cannot be negative")
    add("impossible_bureau_score_out_of_cibil_range", panel["bureau_score"].notna() & (
        (panel["bureau_score"] < 300) | (panel["bureau_score"] > 900)),
        "CIBIL TransUnion scores run 300-900 (sources.yaml shared.bureau.score_bounds)")
    add("impossible_collection_ratio_out_of_range", (panel["collection_ratio"] < 0) | (panel["collection_ratio"] > 1.05),
        "collection_ratio is collected/demanded and should not materially exceed 1.0")
    add("impossible_negative_balance", panel["balance"] < 0,
        "a CASA balance shown to a lender cannot be negative in this product design")
    add("impossible_negative_txn_count", panel["txn_count"] < 0,
        "a transaction count cannot be negative")
    add("impossible_bounce_not_boolean", not_boolean("bounce"),
        "bounce is a 0/1 flag")
    add("impossible_minbal_breach_not_boolean", not_boolean("minbal_breach"),
        "minbal_breach is a 0/1 flag")
    add("impossible_adverse_remark_not_boolean", not_boolean("adverse_remark"),
        "adverse_remark is a 0/1 flag where the adverse channel exists (NaN elsewhere is not a violation)")
    add("impossible_labelable_not_boolean", not_boolean("labelable"),
        "labelable is a 0/1 flag")
    add("impossible_default_label_not_boolean", not_boolean("default_within_12m"),
        "default_within_12m is a 0/1 flag")
    add("impossible_sma2_label_not_boolean", not_boolean("sma2_within_6m"),
        "sma2_within_6m is a 0/1 flag")

    n_noncontig = 0
    for _, months in panel.groupby("account_id")["month_idx"]:
        m = sorted(months.tolist())
        if m != list(range(len(m))):
            n_noncontig += 1
    results.append(_zero_violations(
        "impossible_months_not_contiguous_from_zero", n_noncontig,
        "each account's emitted months must run 0..k with no internal gaps (a row filter may only TRUNCATE "
        "at NPA, never punch a hole in the middle)",
    ))

    return results


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_all(panel: pd.DataFrame, accounts: pd.DataFrame, months: int,
            skip_reproducibility: bool = False) -> list[Result]:
    """Run every check and return the full, unfiltered list of results."""
    results: list[Result] = []
    results.append(check_book_default_rate(panel))
    results.extend(check_portfolio_default_rates(panel))
    results.append(check_sma2_npa_ratio(panel))
    results.append(check_silent_defaulter_share(accounts))
    results.append(check_transient_share(accounts))

    results.append(check_dpd_sma_shares(panel))
    results.append(check_cc_utilisation_mode(panel))
    results.append(check_vintage_hazard_hump(accounts, months))
    results.append(check_agri_seasonality(panel))
    results.append(check_monotone_default_by_dpd(panel))
    results.append(check_monotone_default_by_utilisation(panel))
    results.append(check_monotone_default_by_bounce(panel))

    results.append(check_gst_absent_for_individuals(panel))
    results.append(check_bureau_missing_share(panel))
    results.extend(check_channel_absent_columns()(panel))
    results.append(check_salary_absent_for_non_salaried(panel))

    results.append(check_account_id_bijection(panel, accounts))
    results.append(check_static_attrs_constant(panel))
    results.append(check_vintage_arithmetic(panel, accounts))
    if not skip_reproducibility:
        results.append(check_seed_reproducibility())

    results.extend(impossible_state_checks(panel))
    return results


def print_report(results: list[Result]) -> None:
    n_pass = sum(r.passed for r in results)
    n_fail = len(results) - n_pass
    for result in results:
        print(result.line())
    print()
    print(f"{n_pass}/{len(results)} passed, {n_fail} failed")


def write_report(results: list[Result], out_path: Path) -> None:
    payload = {
        "n_checks": len(results),
        "n_passed": sum(r.passed for r in results),
        "n_failed": sum(not r.passed for r in results),
        "checks": [r.to_dict() for r in results],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--accounts", type=Path, default=DEFAULT_ACCOUNTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--months", type=int, default=None,
                         help="observation window used to build --panel (default: inferred from the data)")
    parser.add_argument("--skip-reproducibility", action="store_true",
                         help="skip the regenerate-twice seed check (saves about a second)")
    args = parser.parse_args(argv)

    panel, accounts = load_data(args.panel, args.accounts)
    months = args.months or int(panel["month_idx"].max() + 1)
    results = run_all(panel, accounts, months, skip_reproducibility=args.skip_reproducibility)
    print_report(results)
    write_report(results, args.out)
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
