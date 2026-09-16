"""SD-D3 — one latent stress, eight sets of instruments.

Three claims are under test here, and the whole "one holistic model across all
borrower types" mandate rests on them:

1. **Each portfolio sees only its own channels.**  A column the bank cannot
   observe for a product is NaN — never zero, never imputed.
2. **Each portfolio's chain is ordered.**  Its first link moves months before
   days-past-due does, so the model has something to learn that is not arrears.
3. **The latent is shared and the channels are not.**  Change a portfolio's
   observation parameters and its observations move; who defaults, and when,
   does not.  That is the generative statement that makes one model across
   eight products legitimate rather than convenient.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from _summary import baselines_by_account, signal_lead
from generator import GeneratorConfig, generate
from generator import portfolios as registry
from generator.channels import CHANNEL_COLUMNS, SHARED_COLUMNS
from generator.portfolios import PORTFOLIOS

#: the vectorised maths must not silently overflow or divide by zero
pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

#: each portfolio's chain: (first link, rule, threshold) as declared in the
#: build plan.  ``rel_*`` rules compare against the account's own healthy
#: baseline, which is how one rule can span a KCC crop receipt and a home-loan
#: salary credit without pretending they are the same size.
CHAINS: dict[str, tuple[str, str, float]] = {
    # GST sales -> utilisation -> bounces -> DPD
    "msme_cc": ("gst_sales", "rel_lt", 0.85),
    # EMI coverage -> part-payment -> DPD
    "msme_tl": ("collection_ratio", "lt", 0.95),
    # salary gap -> balance-floor breach -> EMI bounce -> DPD
    "housing": ("salary_vs_6m_avg", "lt", -0.15),
    # moratorium end -> payment stop -> DPD
    "education": ("collection_ratio", "lt", 0.95),
    # harvest miss (seasonal) -> renewal overdue -> DPD
    "agri": ("crop_receipt_vs_norm", "lt", -0.25),
    # EMI stacking -> min-balance -> bounce -> DPD
    "retail_unsecured": ("emi_burden_ratio", "rel_gt", 1.15),
    # LTV deterioration + rental dip -> DPD
    "lap": ("rental_vs_6m_avg", "lt", -0.20),
    # commute spend + salary gap -> DPD
    "auto": ("commute_spend", "rel_lt", 0.70),
}

#: the chain's first link must lead days-past-due by at least this many months
MIN_LEAD_MONTHS = 4.0

#: and it must fire for at least this share of the portfolio's defaulters
MIN_COVERAGE = 0.80


# --------------------------------------------------------------------------- #
# 1. each portfolio sees only its own instruments
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_declared_channels_are_observed(key: str, panel) -> None:
    """Every column of a declared channel has values for that portfolio."""
    portfolio = PORTFOLIOS[key]
    rows = panel[panel.portfolio == portfolio.code]
    for channel in portfolio.channels:
        for column in CHANNEL_COLUMNS[channel]:
            assert rows[column].notna().all(), f"{key}: {channel}.{column} has gaps"


@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_absent_channels_are_nan(key: str, panel) -> None:
    """A column the bank cannot observe is NaN for every row of that portfolio.

    NaN, not zero: LightGBM reads NaN as "not observed", and the SD-D4
    missingness work needs zero to keep meaning "observed, and it was zero".
    """
    portfolio = PORTFOLIOS[key]
    rows = panel[panel.portfolio == portfolio.code]
    for channel in portfolio.absent_channels:
        for column in CHANNEL_COLUMNS[channel]:
            assert rows[column].isna().all(), f"{key}: {channel}.{column} leaked values"


def test_the_shared_spine_is_never_blank(panel) -> None:
    """DPD, demand, collection, balance and months-on-book exist everywhere.

    Only the bureau score is allowed to go missing, and only for the ~7% of
    borrowers who have no file.
    """
    for column in SHARED_COLUMNS:
        if column == "bureau_score":
            continue
        assert panel[column].notna().all(), column
    for column in ("dpd", "vintage_months", "inflow", "txn_count", "bounce"):
        assert panel[column].notna().all(), column


def test_every_channel_belongs_to_someone(panel) -> None:
    """No declared channel is dead weight across the whole registry."""
    declared = {channel for p in PORTFOLIOS.values() for channel in p.channels}
    assert declared == set(CHANNEL_COLUMNS), sorted(set(CHANNEL_COLUMNS) - declared)
    for channel, columns in CHANNEL_COLUMNS.items():
        for column in columns:
            assert panel[column].notna().any(), f"{channel}.{column} is empty everywhere"


def test_no_portfolio_observes_everything(panel) -> None:
    """If one portfolio saw every channel, the wide panel would prove nothing."""
    for portfolio in PORTFOLIOS.values():
        assert portfolio.absent_channels, portfolio.key


# --------------------------------------------------------------------------- #
# 2. each chain is ordered
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(CHAINS))
def test_the_chain_leads_days_past_due(key: str, panel) -> None:
    """The first link of the chain moves months before the arrears do.

    This is the early-warning thesis, asserted per portfolio rather than
    pooled: if a portfolio's only usable signal were its DPD, a single model
    would be reading arrears for that product and predicting for the others.
    """
    portfolio = PORTFOLIOS[key]
    rows = panel[panel.portfolio == portfolio.code]
    column, rule, threshold = CHAINS[key]
    base = baselines_by_account(rows, [column]) if rule.startswith("rel") else None

    lead, coverage = signal_lead(rows, column, rule, threshold, base)
    dpd_lead, _ = signal_lead(rows, "dpd", "gt", 0.0)
    assert coverage >= MIN_COVERAGE, f"{key}: {column} fires for only {coverage:.2f}"
    assert lead - dpd_lead >= MIN_LEAD_MONTHS, (
        f"{key}: {column} leads by {lead - dpd_lead:.0f} months "
        f"({lead:.0f} vs dpd {dpd_lead:.0f}); need {MIN_LEAD_MONTHS:.0f}"
    )


def test_the_shared_collection_signal_leads_everywhere(panel) -> None:
    """Money stopping is visible before the account is late, in all eight.

    ``collection_ratio`` is the one dynamic column every portfolio carries, so
    it is the spine a single model leans on when a product's own instrument is
    quiet.
    """
    dpd_lead, _ = signal_lead(panel, "dpd", "gt", 0.0)
    for portfolio in PORTFOLIOS.values():
        rows = panel[panel.portfolio == portfolio.code]
        lead, coverage = signal_lead(rows, "collection_ratio", "lt", 0.95)
        assert coverage >= 0.75, f"{portfolio.key}: {coverage:.2f}"
        assert lead > dpd_lead, f"{portfolio.key}: {lead} vs {dpd_lead}"


def test_stress_shows_in_the_chain_before_it_shows_in_the_arrears(panel) -> None:
    """Twelve months out, the chains have moved and days-past-due has not."""
    far = panel[(panel.months_to_npa >= 10) & (panel.months_to_npa <= 12)]
    healthy = panel[panel.months_to_npa < 0]
    assert far.dpd.mean() < 0.5, "arrears must be quiet a year out"
    assert far.collection_ratio.mean() < healthy.collection_ratio.mean()


# --------------------------------------------------------------------------- #
# 3. the latent is shared; the channels are not
# --------------------------------------------------------------------------- #
def test_channel_parameters_move_observations_but_not_fate(monkeypatch) -> None:
    """Re-tune one portfolio's instruments; the latent draw must not budge.

    This is the generative claim in a single assertion.  ``S_t`` is drawn once,
    for the whole book, before any channel exists; a portfolio only decides how
    that stress is *measured*.  So changing housing's elasticities has to change
    housing's observations, leave every other portfolio untouched, and leave
    who-defaults-and-when identical for all eight.
    """
    config = GeneratorConfig(n_accounts=9_000, months=36)
    before_panel, before_accounts = generate(config)

    housing = registry.PORTFOLIOS["housing"]
    monkeypatch.setitem(
        registry.PORTFOLIOS,
        "housing",
        replace(housing, params=replace(
            housing.params,
            salary_elasticity=0.95,
            salary_miss_gain=0.70,
            collection_shortfall_gain=0.95,
            balance_elasticity=0.99,
        )),
    )
    after_panel, after_accounts = generate(config)

    fate = ["account_id", "portfolio", "is_defaulter", "npa_month", "severity",
            "onset", "risk_z", "sanctioned_amount"]
    assert before_accounts[fate].equals(after_accounts[fate]), "the latent draw moved"

    code = housing.code
    observed = ["salary_credit", "collection_ratio", "balance"]
    before_housing = before_panel.loc[before_panel.portfolio == code, observed]
    after_housing = after_panel.loc[after_panel.portfolio == code, observed]
    assert not before_housing.reset_index(drop=True).equals(
        after_housing.reset_index(drop=True)
    ), "housing's observations did not respond to its own parameters"

    other = PORTFOLIOS["agri"].code
    columns = ["crop_receipt", "collection_ratio", "utilisation", "dpd"]
    before_agri = before_panel.loc[before_panel.portfolio == other, columns]
    after_agri = after_panel.loc[after_panel.portfolio == other, columns]
    assert before_agri.reset_index(drop=True).equals(after_agri.reset_index(drop=True)), (
        "changing housing's channels perturbed agri"
    )


def test_one_stress_path_reaches_every_portfolio(panel, accounts) -> None:
    """Severity is drawn once per borrower and every channel answers to it.

    A steeper latent slide has to deepen the observation in each portfolio's
    own instrument, with no per-portfolio severity anywhere in the model.
    """
    severity = accounts.set_index("account_id").severity
    rows = panel[(panel.months_to_npa >= 1) & (panel.months_to_npa <= 6)].copy()
    rows["severity"] = rows.account_id.map(severity)
    steep = rows.severity > rows.severity[rows.severity > 0].median()
    for portfolio in PORTFOLIOS.values():
        block = rows[rows.portfolio == portfolio.code]
        mask = steep[block.index]
        assert block.loc[mask, "collection_ratio"].mean() < (
            block.loc[~mask, "collection_ratio"].mean()
        ), portfolio.key


# --------------------------------------------------------------------------- #
# seasonality — the agri channel is the only one with a calendar
# --------------------------------------------------------------------------- #
def test_crop_receipts_follow_the_crop_calendar(panel) -> None:
    """Kharif sells in October-November, rabi in April-June, and the rest is lean.

    A KCC account is the one place in this book where the calendar, not the
    borrower, drives the cash — which is why ``crop_receipt_vs_norm``
    (seasonally adjusted) and not ``crop_receipt`` is the chain's first link.
    """
    from generator import sources

    agri = panel[panel.portfolio == PORTFOLIOS["agri"].code].copy()
    agri["calendar_month"] = agri.date.astype(str).str.slice(5, 7).astype(int)
    monthly = agri.groupby("calendar_month").crop_receipt.mean()

    harvest = set(sources.value("shared.seasonality.kharif_harvest_months")) | set(
        sources.value("shared.seasonality.rabi_harvest_months")
    )
    lean = sorted(set(range(1, 13)) - harvest)
    assert monthly.loc[sorted(harvest)].min() > 3 * monthly.loc[lean].max(), (
        monthly.round(0).to_dict()
    )


def test_only_agriculture_has_a_season(panel) -> None:
    """No other portfolio's cash flow is a function of the calendar month.

    Seasonal confounders on the non-agri portfolios are SD-D4's job; if they
    already existed here, SD-D4 could not tell its own effect from this one.
    """
    frame = panel.copy()
    frame["calendar_month"] = frame.date.astype(str).str.slice(5, 7).astype(int)
    for portfolio in PORTFOLIOS.values():
        if portfolio.key == "agri":
            continue
        rows = frame[frame.portfolio == portfolio.code]
        monthly = rows.groupby("calendar_month").inflow.mean()
        assert monthly.std() / monthly.mean() < 0.05, portfolio.key


def test_kcc_renewals_slip_before_the_account_goes_bad(panel) -> None:
    """The renewal is annual, so it is sparse — but it points the right way."""
    agri = panel[panel.portfolio == PORTFOLIOS["agri"].code]
    stressed = agri[(agri.months_to_npa >= 1) & (agri.months_to_npa <= 12)]
    healthy = agri[agri.months_to_npa < 0]
    assert (stressed.renewal_overdue_months > 0).mean() > 3 * (
        healthy.renewal_overdue_months > 0
    ).mean()


# --------------------------------------------------------------------------- #
# impossible states
# --------------------------------------------------------------------------- #
def test_nothing_impossible_is_emitted(panel) -> None:
    """Bounds a bank reviewer would check first."""
    assert (panel.collected_amount <= panel.demanded_amount + 1).all()
    assert (panel.collection_ratio.between(0.0, 1.0)).all()
    assert (panel.demanded_amount >= 0).all()
    assert (panel.balance >= 0).all()
    assert (panel.outstanding >= 0).all()
    assert (panel.min_balance_6m <= panel.balance + 1).all()
    for column in ("ltv", "salary_credit", "rental_income", "crop_receipt",
                   "commute_spend", "other_bank_emi", "drawing_power"):
        values = panel[column].dropna()
        assert (values >= 0).all(), column
        assert np.isfinite(values).all(), column


def test_the_moratorium_suppresses_the_demand(panel) -> None:
    """No EMI is demanded during a course moratorium, and it resumes after."""
    education = panel[panel.portfolio == PORTFOLIOS["education"].code]
    active = education.moratorium_active == 1
    assert active.any() and (~active).any()
    assert (education.loc[active, "demanded_amount"] == 0).all()
    assert (education.loc[~active, "demanded_amount"] > 0).all()
    assert (education.loc[active, "months_since_moratorium_end"] < 0).all()


def test_drawing_power_never_exceeds_the_sanctioned_limit(panel, accounts) -> None:
    """A drawing power is computed against stock and book debts, inside the limit."""
    limit = accounts.set_index("account_id").sanctioned_amount
    rows = panel[panel.drawing_power.notna()]
    assert (rows.drawing_power <= rows.account_id.map(limit) + 1).all()
