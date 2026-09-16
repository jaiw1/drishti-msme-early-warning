"""SD-D2 — the population: eight portfolios, five constitutions, real tickets.

What this suite is really asserting is that the *book* is a book: the mix a
bank would recognise, ticket sizes in the right order of magnitude for each
product, individuals where individuals borrow and companies where companies do,
geography that is not uniform, and a default rate per portfolio that a credit
reviewer would not laugh at.

Every band it checks comes from ``src/generator/sources.yaml`` — the test reads
the same node the generator does, so a parameter can never drift away from the
assertion that guards it.
"""

from __future__ import annotations

import numpy as np
import pytest

from generator import sources
from generator.portfolios import PORTFOLIOS

#: how far a realised share may sit from its declared one, in percentage points
SHARE_TOLERANCE_PP = 1.5

#: the whole book's annual slippage band, pre-registered as DR-03 in
#: ``validation/criteria.yaml`` (plan gate G2, "slippage 3-5%")
BOOK_RATE_BAND = (0.03, 0.05)

RETAIL_KEYS = ("housing", "education", "retail_unsecured", "auto")
BUSINESS_KEYS = ("msme_cc", "msme_tl", "lap")


def _labelable(panel):
    """Rows whose full twelve-month forward window is inside the panel."""
    return panel[panel.labelable == 1]


# --------------------------------------------------------------------------- #
# the mix
# --------------------------------------------------------------------------- #
def test_portfolio_mix_matches_the_sourced_shares(accounts) -> None:
    """Every portfolio lands in the book at the share ``sources.yaml`` declares."""
    observed = accounts.portfolio.value_counts(normalize=True)
    assert set(observed.index) == {p.code for p in PORTFOLIOS.values()}
    for portfolio in PORTFOLIOS.values():
        delta = abs(observed[portfolio.code] - portfolio.share) * 100
        assert delta <= SHARE_TOLERANCE_PP, (
            f"{portfolio.key}: {observed[portfolio.code]:.3f} vs {portfolio.share:.3f}"
        )


def test_no_portfolio_is_too_thin_to_evaluate(accounts) -> None:
    """Criterion DR-06 asks for a per-portfolio AUC with a CI, on all eight.

    The mix is deliberately shrunk toward uniform for exactly this reason (see
    ``book.mix_shrinkage_lambda``); this is the assertion that keeps the
    shrinkage doing its job.
    """
    counts = accounts.portfolio.value_counts()
    assert counts.min() >= 0.05 * len(accounts), counts.to_dict()


# --------------------------------------------------------------------------- #
# constitutions — the axis SD-D4's GST missingness will hang off
# --------------------------------------------------------------------------- #
def test_individuals_dominate_the_retail_portfolios(accounts) -> None:
    """A home, education, personal or vehicle loan is written to a person."""
    for key in RETAIL_KEYS:
        rows = accounts[accounts.portfolio == PORTFOLIOS[key].code]
        share = (rows.constitution == "Individual").mean()
        assert share >= 0.75, f"{key}: Individual share {share:.2f}"


def test_business_portfolios_carry_real_constitutions(accounts) -> None:
    """MSME and LAP books are mostly firms and companies, not individuals."""
    for key in BUSINESS_KEYS:
        rows = accounts[accounts.portfolio == PORTFOLIOS[key].code]
        assert (rows.constitution == "Individual").mean() <= 0.5, key
        assert rows.constitution.nunique() >= 3, key


def test_gst_exists_exactly_where_a_gst_return_would(panel) -> None:
    """The GST channel belongs to the business portfolios, and to their firms.

    Two rules, and the panel now carries both.  The structural half is the
    portfolio: a home loan has no GST channel at all, so the column is NaN for
    every row.  The conditional half is SD-D4's: inside a portfolio that DOES
    carry the channel, an Individual borrower files no return, so their rows
    are NaN too.  LAP is where both meet, at roughly two in five borrowers.
    """
    for portfolio in PORTFOLIOS.values():
        rows = panel[panel.portfolio == portfolio.code]
        if not portfolio.has("gst"):
            assert rows.gst_sales.isna().all(), portfolio.key
            continue
        filing = rows.constitution.astype(str) != "Individual"
        assert rows.loc[filing, "gst_sales"].notna().all(), portfolio.key
        assert rows.loc[~filing, "gst_sales"].isna().all(), portfolio.key
    lap = PORTFOLIOS["lap"]
    assert lap.has("gst")
    lap_rows = panel[panel.portfolio == lap.code]
    assert 0.2 < (lap_rows.constitution == "Individual").mean() < 0.7


def test_the_gst_filing_hook_names_the_right_forms(accounts) -> None:
    """``files_gst`` is the per-borrower half of the missingness story.

    Portfolio-level absence covers the products where nobody files a return;
    this is the hook SD-D4 needs inside a portfolio that does carry a GST
    channel, where an Individual borrower still files nothing.
    """
    from generator.constitutions import constitution_levels, files_gst

    levels = constitution_levels()
    assert set(levels) == {"Individual", "Proprietorship", "Partnership", "PvtLtd", "LLP"}
    codes = np.arange(len(levels))
    filing = dict(zip(levels, files_gst(codes, levels)))
    assert filing["Individual"] is np.False_
    assert all(filing[level] for level in levels if level != "Individual")

    lap = accounts[accounts.portfolio == PORTFOLIOS["lap"].code]
    non_filing = (lap.constitution == "Individual").mean()
    assert 0.2 < non_filing < 0.7, (
        f"LAP needs both kinds of borrower for SD-D4 to have anything to do; "
        f"got {non_filing:.2f} individuals"
    )


# --------------------------------------------------------------------------- #
# ticket, tenor, rate, security
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_ticket_distribution_matches_its_sourced_lognormal(key: str, accounts) -> None:
    """Median ticket within 12% of ``exp(log_mean)``, and inside the bounds."""
    portfolio = PORTFOLIOS[key]
    rows = accounts[accounts.portfolio == portfolio.code]
    population = portfolio.population
    assert population is not None
    expected = float(np.exp(population.ticket_log_mean))
    observed = float(rows.sanctioned_amount.median())
    assert abs(observed - expected) / expected < 0.12, (
        f"{key}: median {observed:,.0f} vs {expected:,.0f}"
    )
    low, high = population.ticket_bounds
    assert rows.sanctioned_amount.min() >= low - 1
    assert rows.sanctioned_amount.max() <= high + 1


def test_tickets_are_ordered_the_way_the_products_are(accounts) -> None:
    """A home loan is bigger than a vehicle loan is bigger than a KCC limit."""
    median = accounts.groupby("portfolio", observed=True).sanctioned_amount.median()
    assert median["Housing"] > median["LAP"] > median["Auto"] > median["Agri"]
    assert median["Auto"] > median["Retail-Unsecured"] > median["Agri"]


@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_tenor_and_rate_stay_inside_their_bands(key: str, accounts) -> None:
    """Nothing is priced or written outside the band ``sources.yaml`` records."""
    portfolio = PORTFOLIOS[key]
    rows = accounts[accounts.portfolio == portfolio.code]
    population = portfolio.population
    assert population is not None
    tenor_low, tenor_high = population.tenor_bounds
    assert rows.tenor_months.min() >= tenor_low
    assert rows.tenor_months.max() <= tenor_high
    rate_low, rate_high = population.rate_bounds
    assert rows.interest_rate_pa.min() >= rate_low - 1e-4
    assert rows.interest_rate_pa.max() <= rate_high + 1e-4


@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_security_matches_the_sourced_share(key: str, accounts) -> None:
    """Housing, LAP and Auto are always secured; personal loans never are."""
    portfolio = PORTFOLIOS[key]
    rows = accounts[accounts.portfolio == portfolio.code]
    population = portfolio.population
    assert population is not None
    observed = float(rows.secured.mean())
    assert abs(observed - population.secured_share) < 0.05, f"{key}: {observed:.3f}"


def test_vintage_respects_the_products_life(accounts) -> None:
    """A twenty-year mortgage book carries older accounts than a KCC book."""
    for key, portfolio in PORTFOLIOS.items():
        population = portfolio.population
        assert population is not None
        rows = accounts[accounts.portfolio == portfolio.code]
        low, high = population.vintage_bounds
        assert rows.vintage_months_0.min() >= low, key
        assert rows.vintage_months_0.max() < high, key
    median = accounts.groupby("portfolio", observed=True).vintage_months_0.median()
    assert median["Housing"] > median["Agri"]


# --------------------------------------------------------------------------- #
# geography and sector
# --------------------------------------------------------------------------- #
def test_state_is_always_inside_its_region(accounts) -> None:
    """The new ``state`` column refines ``region``; it never contradicts it."""
    within = sources.value("shared.states_within_region")
    for region, states in within.items():
        rows = accounts[accounts.region == region]
        assert set(rows.state.unique()) <= set(states), region
    assert accounts.state.nunique() >= 20


def test_city_tier_uses_rbis_population_groups(accounts) -> None:
    """Rural / Semi-Urban / Urban / Metropolitan, and agri is the rural one."""
    assert set(accounts.city_tier.unique()) == {
        "Rural", "Semi-Urban", "Urban", "Metropolitan"
    }
    rural = accounts.groupby("portfolio", observed=True).city_tier.apply(
        lambda s: (s == "Rural").mean()
    )
    assert rural["Agri"] > 0.5
    assert rural["Housing"] < 0.1


def test_nic_group_is_present_exactly_for_enterprises(accounts) -> None:
    """A salaried borrower runs no enterprise, so it has no NIC group."""
    salaried = accounts.sector == "Salaried"
    assert accounts.loc[salaried, "nic_group"].isna().all()
    assert accounts.loc[~salaried, "nic_group"].notna().all()
    assert accounts.loc[accounts.sector == "Agriculture", "nic_group"].unique().tolist() == [
        "NIC 01-03 Agriculture, forestry and fishing"
    ]


def test_sector_mix_is_portfolio_specific(accounts) -> None:
    """MSME borrowers trade and manufacture; home-loan borrowers are salaried."""
    salaried = accounts.groupby("portfolio", observed=True).sector.apply(
        lambda s: (s == "Salaried").mean()
    )
    assert salaried["Housing"] > 0.6
    assert salaried["MSME-CC"] == 0.0
    assert salaried["Agri"] == 0.0


# --------------------------------------------------------------------------- #
# bureau file
# --------------------------------------------------------------------------- #
def test_seven_percent_of_borrowers_have_no_bureau_file(panel) -> None:
    """Criterion DR-23 stress-tests the model against a missing bureau file."""
    expected = sources.value("shared.bureau.missing_share")
    observed = panel.bureau_score.isna().mean()
    assert abs(observed - expected) < 0.01, f"{observed:.3f} vs {expected}"
    scored = panel.bureau_score.dropna()
    low, high = sources.value("shared.bureau.score_bounds")
    assert scored.min() >= low and scored.max() <= high


# --------------------------------------------------------------------------- #
# the default rates — the numbers a credit reviewer reads first
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_portfolio_default_rate_is_in_its_sourced_band(key: str, panel) -> None:
    """Each portfolio's realised 12-month rate sits inside its sourced band.

    The bands, and where they come from, are in ``sources.yaml``:

    * Housing 0.8-1.6% — RBI's Personal Loans bucket is 1.2% and the unsecured
      slice inside it is 1.8%, so secured housing sits below 1.2%.
    * Education 1.5-4.0% — 2% at public-sector banks in FY25, down from 7% in
      FY21 (Minister of State for Finance, Lok Sabha, Dec-2025).
    * Agri 4.5-8.0% — 6.10% at Mar-2025, the highest of any major sector.
    * MSME 2.8-4.5% — MSME Pulse delinquency by exposure band, 5.8% up to
      10 lakh and 2.9% for 10-50 lakh, and this book's median ticket is 12 lakh.
    * Retail-unsecured 1.4-3.2% — RBI FSR June 2025 puts unsecured retail at 1.8%.
    * LAP 1.8-3.8% and Auto 1.0-2.6% — no public figure exists for either;
      both are reasoned between housing and MSME and recorded as ``assumed``.
    """
    portfolio = PORTFOLIOS[key]
    rows = _labelable(panel)
    rate = float(rows.loc[rows.portfolio == portfolio.code, "default_within_12m"].mean())
    low, high = portfolio.default_rate_band
    assert low <= rate <= high, f"{key}: {rate:.4f} outside [{low}, {high}]"


def test_the_book_slips_at_a_rate_a_reviewer_recognises(panel) -> None:
    """The whole book's annual rate lands in the pre-registered DR-03 band.

    It is NOT IDBI's own rate — IDBI reported 0.63% net slippage in FY26.  The
    generator targets system-wide sectoral GNPA instead, which is roughly five
    times that, and the gap is recorded in ``sources.yaml`` and belongs in
    ``DATA_CARD.md``.  What this test guards is that the portfolio-level
    calibration still aggregates into the band the validation pack registered
    before any model existed.
    """
    rate = float(_labelable(panel).default_within_12m.mean())
    low, high = BOOK_RATE_BAND
    assert low <= rate <= high, f"{rate:.4f} outside [{low}, {high}]"


def test_the_rates_are_ordered_the_way_the_products_are(panel) -> None:
    """Agri worst, housing best — the ordering a credit committee would expect."""
    rows = _labelable(panel)
    rate = rows.groupby("portfolio", observed=True).default_within_12m.mean()
    assert rate["Agri"] > rate["MSME-CC"] > rate["Housing"]
    assert rate["Agri"] > rate["Education"] > rate["Housing"]
    assert rate["Retail-Unsecured"] > rate["Housing"]


def test_the_annual_rate_does_not_move_with_the_window() -> None:
    """A 48-month panel reports the same annual rate as a 36-month one.

    Without the hazard rescaling in :func:`generator.latent.draw_population`, a
    longer observation window spreads the same defaulters over more months and
    quietly thins every rate quoted off the panel — which would make the bands
    above a property of ``--months`` rather than of the book.
    """
    from generator import GeneratorConfig, generate

    rates = []
    for months in (36, 48):
        frame, _ = generate(GeneratorConfig(n_accounts=12_000, months=months))
        rates.append(float(frame.loc[frame.labelable == 1, "default_within_12m"].mean()))
    assert abs(rates[0] - rates[1]) < 0.005, rates
