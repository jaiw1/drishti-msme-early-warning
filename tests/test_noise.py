"""SD-D4/SD-D5 — the population a real book has that a clean simulator does not.

The July 2026 panel, and SD-D3's eight-portfolio extension of it, had a book in
which *every* defaulter showed *every* link of its chain, no healthy account
ever went past due and cured, no calendar effect ever moved a healthy series in
the same direction stress does, and every instrument reported the truth on
time.  A LightGBM scored it at 0.97 grouped AUC.  Published bank early-warning
models land near 0.81, and the pre-registered band (DR-01) is [0.82, 0.92].

This suite asserts the five mechanisms that close that gap, and the two labels
that hang off them:

1. **Silent and fast defaulters** — a per-portfolio share of defaulters with no
   warning chain at all.  They are the honest ceiling on any model.
2. **Transient stress** — recoverable episodes on healthy accounts that move
   the portfolio's own first link, part-pay the instalment and, for a share of
   them, go genuinely past due before curing.  Every row of every episode is a
   zero the model has to earn.
3. **Seasonal confounders** — festival, post-festival, quarter-end, fiscal-year
   start, monsoon and bonus effects that make healthy accounts move the way
   sliding ones do.
4. **MAR missingness** — no GST return for an Individual, no salary credit for
   the self-employed, no bureau file for 7% of borrowers, and statement-feed
   gaps drawn from a stream that has never seen the label.
5. **Measurement noise** — GST reporting lags, rounding, duplicated batches,
   reversed payments, stale collateral and bureau pulls, and the idiosyncratic
   noise every real income series carries.

And the labels: ``default_within_12m`` keeps its meaning and its base rate,
``sma2_within_6m`` is new, and both are asserted in-script rather than hoped
for.

What this suite deliberately does NOT do is check that the AUC is in band by
making the data easier.  The AUC diagnostic at the bottom is a *measurement*:
it fits the same quick LightGBM SD-D2/SD-D3 used, on three seeds, and reports
what it finds.  If the mechanisms above at their sourced shares do not put the
book in band, the right answer is to say so, not to move a share.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from _summary import (
    CHAINS,
    SPINE_RULES,
    baselines_by_account,
    first_warning_leads,
    sustained_lead,
)
from generator import GeneratorConfig, generate, sources
from generator.channels import CHANNEL_COLUMNS, confounder_profile
from generator.constitutions import files_gst
from generator.labels import SMA2_DPD, assert_base_rates, measure_base_rates
from generator.portfolios import POPULATION, PORTFOLIOS

#: the vectorised maths must not silently overflow or divide by zero
pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

#: the median chain-defaulter must be warned this many months before NPA
MIN_FIRST_WARNING_MONTHS = 8.0

#: a silent defaulter's first link may not lead by more than this
MAX_SILENT_LEAD_MONTHS = 2.0

#: how far a realised silent share may sit from its configured one
SILENT_SHARE_TOLERANCE_PP = 1.5

#: Accounts the AUC diagnostic fits on.  It has to be large enough for DR-06's
#: per-portfolio floor to be a property of the BOOK rather than of the sample:
#: at 12,000 accounts the thinnest portfolio trains on a few hundred defaulters
#: and vehicle finance lands below 0.78 for want of data, while at 24,000 it
#: sits where the 45,000-account validation population puts it.  The pooled
#: figure moves much less — about half a point between the two.
AUC_ACCOUNTS = 24_000

#: months a transient dip is averaged over before it counts as an episode
SUSTAINED_WINDOW = 4

#: how much worse an episode account's worst run must be than a quiet
#: account's.  Deliberately small: several of these instruments are noisy
#: enough that a 30% income shock lasting four months moves the smoothed
#: extreme by only a few points — vehicle finance's card-visible fuel spend
#: worst of all — and a larger required gap would be asserting that the
#: instruments are cleaner than SD-D4 makes them.
MIN_EPISODE_DIP = 0.05

#: The instrument an episode is judged on, where it is not the chain's own
#: first link.  Vehicle finance is the exception: a transient episode does cut
#: card-visible fuel spend (``shared.transient.income_multiple``), but that
#: series carries a 0.38 log-sd of idiosyncratic noise and a 7% chance of
#: showing nothing at all in a month, so a four-month smoothed comparison
#: cannot separate an episode from an ordinary quarter.  Auto's episodes are
#: therefore judged on the salary credit, which is the other half of the
#: build plan's "commute spend + salary gap" chain and the half a bank can
#: actually read.  This is a statement about the instrument, not about the
#: mechanism: the episode moves both.
EPISODE_LINKS: dict[str, tuple[str, str]] = {"auto": ("salary_credit", "rel_lt")}


def _accounts_of(panel: pd.DataFrame, key: str) -> pd.DataFrame:
    return panel[panel.portfolio == PORTFOLIOS[key].code]


def _split(rows: pd.DataFrame, silent: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a portfolio's rows into chain defaulters' and silent defaulters'."""
    flag = rows.account_id.isin(silent)
    return rows[~flag], rows[flag]


@pytest.fixture(scope="module")
def silent_ids(accounts) -> set[str]:
    """Accounts whose default arrives with no warning chain."""
    return set(accounts.loc[accounts.silent_default == 1, "account_id"])


# --------------------------------------------------------------------------- #
# 1. silent and fast defaulters
# --------------------------------------------------------------------------- #
def test_silent_share_per_portfolio_matches_the_config() -> None:
    """Each portfolio's silent share lands within 1.5 pp of ``sources.yaml``.

    Drawn on a population large enough for 1.5 pp to mean something: at the
    24,000-account book the thinnest portfolio has a few hundred defaulters, so
    a binomial standard error alone is wider than the tolerance.  Only the
    cross-section is drawn here — no channels — so 240,000 accounts costs about
    a second.
    """
    from generator.latent import draw_population

    population, portfolios = draw_population(
        GeneratorConfig().seed, 240_000, 48, POPULATION
    )
    defaulting = population.is_defaulter
    for code, portfolio in enumerate(portfolios):
        rows = defaulting & (population.portfolio_code == code)
        observed = float(population.silent[rows].mean())
        assert abs(observed - portfolio.silent_share) * 100 <= SILENT_SHARE_TOLERANCE_PP, (
            f"{portfolio.key}: {observed:.4f} vs configured {portfolio.silent_share} "
            f"(n={int(rows.sum())})"
        )


def test_the_book_wide_silent_share_is_the_plans_eight_percent(accounts) -> None:
    """The eight per-portfolio shares weight to the book-wide target."""
    defaulters = accounts[accounts.is_defaulter == 1]
    observed = float(defaulters.silent_default.mean())
    target = POPULATION.silent_book_share
    assert abs(observed - target) <= 0.02, f"{observed:.4f} vs {target}"


@pytest.mark.parametrize("key", sorted(CHAINS))
def test_silent_defaulters_give_no_warning(key: str, panel, silent_ids) -> None:
    """A silent defaulter's chain does not lead its arrears.

    The whole point of the bucket: for these borrowers the first link and the
    days-past-due move together, one or two months before NPA, because the
    cause was a death, a fraud or a job lost with no notice rather than a slide
    anyone could have watched.  The median sustained lead must be at most two
    months — against eight-or-more for the chain defaulters of the same
    portfolio, which the next test asserts.
    """
    column, rule, threshold = CHAINS[key]
    rows = _accounts_of(panel, key)
    observed = rows[rows[column].notna()]
    _, silent = _split(observed, silent_ids)
    if silent.account_id.nunique() < 5:
        pytest.skip(f"{key}: too few silent defaulters in the fixture book")
    base = baselines_by_account(silent, [column]) if rule.startswith("rel") else None

    lead, _ = sustained_lead(silent, column, rule, threshold, base)
    dpd_lead, _ = sustained_lead(silent, "dpd", "gt", 0.0)
    assert lead <= MAX_SILENT_LEAD_MONTHS, (
        f"{key}: silent defaulters warn {lead:.1f} months out on {column}; "
        f"the bucket is defined by having no warning"
    )
    assert lead <= dpd_lead + MAX_SILENT_LEAD_MONTHS, (
        f"{key}: {column} leads DPD by {lead - dpd_lead:.1f} months on accounts "
        f"that are supposed to have no chain"
    )


def test_chain_defaulters_are_still_warned_a_long_way_out(panel, silent_ids) -> None:
    """The median chain defaulter is warned at least eight months before NPA.

    Measured the way an early-warning system works: the earliest month at which
    ANY of the account's watched signals — its portfolio's own first link, the
    collection ratio, its banked inflow — is past threshold for three
    consecutive months.  Judging one column at a time understates the lead for
    exactly the borrowers SD-D4 made interesting, the ones whose own product
    signal is dark but whose money has visibly stopped arriving.

    This is the number DRISHTi's headline claim rests on, and SD-D4 is not
    allowed to spend it.
    """
    leads: list[pd.Series] = []
    for key, (column, rule, threshold) in CHAINS.items():
        rows = _accounts_of(panel, key)
        chain, _ = _split(rows, silent_ids)
        found = first_warning_leads(chain, SPINE_RULES + [(column, rule, threshold)])
        if len(found):
            leads.append(found)
    pooled = pd.concat(leads)
    warned = pooled[pooled > 0]
    assert len(warned) / len(pooled) >= 0.90, (
        f"only {len(warned) / len(pooled):.0%} of chain defaulters are warned at all"
    )
    assert warned.median() >= MIN_FIRST_WARNING_MONTHS, (
        f"median first warning is {warned.median():.1f} months before NPA; "
        f"the claim needs {MIN_FIRST_WARNING_MONTHS:.0f}"
    )


def test_a_silent_default_is_not_a_different_kind_of_default(accounts) -> None:
    """Silence is an OBSERVATION property, not a fate.

    A silent defaulter is drawn from the same latent process, in the same
    portfolio, at the same rate: the only thing that changes is how much of the
    slide is visible.  If silence also made an account riskier, the bucket
    would be smuggling a second signal into the panel instead of removing one.
    """
    defaulters = accounts[accounts.is_defaulter == 1]
    silent = defaulters[defaulters.silent_default == 1]
    chain = defaulters[defaulters.silent_default == 0]
    assert abs(silent.risk_z.mean() - chain.risk_z.mean()) < 0.15
    assert abs(silent.npa_month.mean() - chain.npa_month.mean()) < 1.5
    # and the compressed slide is exactly the configured one or two months
    low, high = POPULATION.silent_onset_bounds
    assert silent.onset.between(low, high).all()
    assert (chain.onset >= 5).all()


# --------------------------------------------------------------------------- #
# 2. transient stress — the hard negatives
# --------------------------------------------------------------------------- #
def test_transient_share_per_portfolio_matches_the_config(accounts) -> None:
    """The configured share of never-defaulting accounts gets an episode."""
    healthy = accounts[accounts.is_defaulter == 0]
    for key, portfolio in PORTFOLIOS.items():
        rows = healthy[healthy.portfolio == portfolio.code]
        observed = float((rows.transient_months > 0).mean())
        assert abs(observed - portfolio.params.transient_share) <= 0.03, (
            f"{key}: {observed:.3f} vs configured {portfolio.params.transient_share}"
        )


@pytest.mark.parametrize("key", sorted(CHAINS))
def test_transient_accounts_show_the_first_link_and_do_not_default(
    key: str, panel, accounts
) -> None:
    """A hard negative looks like an early-stage defaulter and is not one.

    Two halves, and both matter:

    * **It shows the link.**  Inside an episode, the portfolio's own first link
      is materially worse than the same account's healthy months — that is what
      makes the row hard rather than merely noisy.
    * **It does not default.**  Episodes are drawn only for accounts that never
      reach NPA, so the realised 12-month default rate on episode rows is
      exactly zero.  The band asserted here is therefore "at the base rate or
      below, and never materially above it": transient stress must not be a
      back-door risk factor, or it would be a signal rather than a confounder.
    """
    portfolio = PORTFOLIOS[key]
    column, rule, _ = CHAINS[key]
    column, rule = EPISODE_LINKS.get(key, (column, rule))
    episodes = set(accounts.loc[accounts.transient_months > 0, "account_id"])
    rows = panel[(panel.portfolio == portfolio.code) & (panel.months_to_npa < 0)]
    rows = rows[rows[column].notna()]
    inside = rows[rows.account_id.isin(episodes)]
    assert len(inside) > 200, f"{key}: too few transient rows to judge"

    outside = rows[~rows.account_id.isin(episodes)]
    base = baselines_by_account(rows, [column])

    def worst(frame: pd.DataFrame) -> float:
        """Median across accounts of each account's worst SUSTAINED run.

        The panel carries no per-row episode flag — it is ground truth, and
        putting it in the panel would hand the model the answer — so the test
        compares an account's worst months against its own healthy level.  An
        account that passed through an episode has a run its neighbour does
        not, which is the whole claim.

        Read over a four-month window rather than a single month, because
        several of these instruments legitimately show a zero in an ordinary
        month: a flat between tenancies, a month the borrower paid for fuel in
        cash.  A one-month rule would find those on every account and separate
        nothing.
        """
        joined = frame.join(base[[column]], on="account_id", rsuffix="_base")
        ratio = (joined[column] / joined[f"{column}_base"].replace(0.0, np.nan)).to_frame(
            "ratio"
        )
        ratio["account_id"] = joined.account_id.to_numpy()
        ratio["month_idx"] = joined.month_idx.to_numpy()
        ratio = ratio.sort_values(["account_id", "month_idx"])
        smoothed = (
            ratio.groupby("account_id", observed=True)
            .ratio.rolling(SUSTAINED_WINDOW, min_periods=SUSTAINED_WINDOW)
            .mean()
            .reset_index(level=0)
        )
        extreme = (
            smoothed.groupby("account_id", observed=True).ratio.min()
            if rule.endswith("lt")
            else smoothed.groupby("account_id", observed=True).ratio.max()
        )
        return float(extreme.median())

    if rule.endswith("lt"):
        assert worst(inside) < (1.0 - MIN_EPISODE_DIP) * worst(outside), (
            f"{key}: episodes do not move {column} "
            f"({worst(inside):.3f} vs {worst(outside):.3f})"
        )
    else:
        assert worst(inside) > (1.0 + MIN_EPISODE_DIP) * worst(outside), (
            f"{key}: episodes do not move {column} "
            f"({worst(inside):.3f} vs {worst(outside):.3f})"
        )

    # the band: episode rows must not carry a default rate above the base rate
    labelable = panel[panel.labelable == 1]
    book = float(labelable.default_within_12m.mean())
    episode_rows = labelable[labelable.account_id.isin(episodes)]
    assert float(episode_rows.default_within_12m.mean()) <= book, (
        "transient stress must be a confounder, not a risk factor"
    )


def test_some_hard_negatives_go_genuinely_past_due_and_cure(panel, accounts) -> None:
    """Days past due is not a synonym for "about to default".

    The July build let an account bounce a payment and stay at 0 DPD, so
    ``dpd > 0`` was a near-perfect classifier.  Here a failed mandate is real
    arrears and a share of transient episodes reaches SMA-1 or SMA-2 before
    curing — so a meaningful population of rows carries a late-payment history
    and a zero label.
    """
    healthy = panel[panel.months_to_npa < 0]
    assert (healthy.dpd > 0).mean() > 0.01, "no healthy account is ever late"
    assert (healthy.dpd_max_6m >= SMA2_DPD).mean() > 0.001, (
        "no healthy account ever reaches SMA-2"
    )
    cured = accounts[(accounts.is_defaulter == 0) & (accounts.transient_arrears == 1)]
    assert len(cured) > 100
    # and they really do cure: none of them is in the panel at 90+ DPD, because
    # the row filter would have dropped it
    rows = panel[panel.account_id.isin(set(cured.account_id))]
    assert rows.dpd.max() < 90.0


def test_the_labels_disagree_with_each_other(panel) -> None:
    """SMA-2 is a different label, not a rescaled copy of the NPA one.

    If every SMA-2 row were also an NPA row the secondary label would carry no
    information the first does not; the cure population is what makes it a
    second measurement.
    """
    rows = panel[panel.labelable == 1]
    both = (rows.sma2_within_6m == 1) & (rows.default_within_12m == 1)
    only_sma2 = (rows.sma2_within_6m == 1) & (rows.default_within_12m == 0)
    assert only_sma2.sum() > 0, "every SMA-2 row is an NPA row — nothing ever cures"
    assert only_sma2.sum() / max(both.sum(), 1) > 0.05


# --------------------------------------------------------------------------- #
# 3. seasonal confounders
# --------------------------------------------------------------------------- #
def test_the_confounder_profile_has_an_annual_mean_of_one() -> None:
    """A confounder moves the shape of a year, never its level.

    If it moved the level it would be a portfolio parameter wearing a calendar
    costume, and it would show up as a difference between portfolios rather
    than as a difference between months.
    """
    calendar = np.arange(1, 13)
    for key, portfolio in PORTFOLIOS.items():
        profile = confounder_profile(
            calendar, portfolio.params, POPULATION, portfolio.has("harvest")
        )
        for signal, cycle in profile.items():
            assert abs(float(cycle.mean()) - 1.0) < 1e-9, f"{key}.{signal}"


def test_the_festival_and_the_lull_reach_healthy_accounts(panel) -> None:
    """The calendar moves accounts that are going nowhere near NPA.

    Measured on never-defaulting rows only, so nothing here can be a stress
    response: the festival months have to carry more inflow than the lull that
    follows them, for the portfolios that declared an amplitude.
    """
    frame = panel[panel.months_to_npa < 0].copy()
    frame["calendar_month"] = frame.date.astype(str).str.slice(5, 7).astype(int)
    festival = set(POPULATION.festival_months)
    lull = set(POPULATION.post_festival_months)
    for key, portfolio in PORTFOLIOS.items():
        if not portfolio.params.season_inflow_amp or portfolio.has("harvest"):
            continue
        rows = frame[frame.portfolio == portfolio.code]
        monthly = rows.groupby("calendar_month").inflow.mean()
        assert monthly.loc[sorted(festival)].mean() > monthly.loc[sorted(lull)].mean(), (
            f"{key}: no festival effect ({monthly.round(0).to_dict()})"
        )


def test_the_harvest_calendar_still_drives_the_kcc_book(panel) -> None:
    """Agri's cash follows the crop, not the shopping calendar."""
    frame = panel[panel.months_to_npa < 0].copy()
    frame["calendar_month"] = frame.date.astype(str).str.slice(5, 7).astype(int)
    agri = frame[frame.portfolio == PORTFOLIOS["agri"].code]
    harvest = sorted(
        set(POPULATION.kharif_harvest_months) | set(POPULATION.rabi_harvest_months)
    )
    lean = sorted(set(range(1, 13)) - set(harvest))
    monthly = agri.groupby("calendar_month").inflow.mean()
    assert monthly.loc[harvest].mean() > monthly.loc[lean].mean()


def test_the_bonus_month_makes_a_later_month_read_short(panel) -> None:
    """A confounder that fools the feature, not just the level.

    An October bonus lifts the trailing six-month average, so November and
    December read below it — the salaried portfolios' own first link, firing on
    a borrower whose pay never changed.
    """
    frame = panel[panel.months_to_npa < 0].copy()
    frame["calendar_month"] = frame.date.astype(str).str.slice(5, 7).astype(int)
    salaried = [p for p in PORTFOLIOS.values() if p.params.season_salary_amp > 0]
    assert salaried
    rows = frame[frame.portfolio.isin([p.code for p in salaried])]
    rows = rows[rows.salary_vs_6m_avg.notna()]
    bonus = set(POPULATION.bonus_months)
    after = {month % 12 + 1 for month in bonus} | {(month + 1) % 12 + 1 for month in bonus}
    monthly = rows.groupby("calendar_month").salary_vs_6m_avg.mean()
    assert monthly.loc[sorted(bonus)].mean() > monthly.loc[sorted(after - bonus)].mean()


# --------------------------------------------------------------------------- #
# 4. MAR missingness
# --------------------------------------------------------------------------- #
def test_an_individual_borrower_never_has_a_gst_return(panel, accounts) -> None:
    """Structural, absolute, and the same rule the constitution module states."""
    levels = tuple(POPULATION.constitution_levels)
    filing = dict(
        zip(levels, files_gst(np.arange(len(levels)), levels))
    )
    individuals = set(
        accounts.loc[accounts.constitution.map(filing).eq(False), "account_id"]
    )
    assert individuals
    rows = panel[panel.account_id.isin(individuals)]
    for column in CHANNEL_COLUMNS["gst"]:
        assert rows[column].isna().all(), column
    # and a GST-bearing portfolio still has borrowers who DO file
    lap = panel[panel.portfolio == PORTFOLIOS["lap"].code]
    assert lap.gst_sales.notna().any() and lap.gst_sales.isna().any()


def test_a_self_employed_borrower_has_no_salary_credit(panel) -> None:
    """The salary channel is dark for the borrowers a bank has no payroll for."""
    for key, portfolio in PORTFOLIOS.items():
        if not portfolio.has("salary"):
            continue
        rows = panel[panel.portfolio == portfolio.code]
        self_employed = rows.sector.astype(str) != "Salaried"
        assert rows.loc[self_employed, "salary_credit"].isna().all(), key
        assert rows.loc[~self_employed, "salary_credit"].notna().any(), key


def test_statement_gaps_are_short_and_uncommon(panel, accounts) -> None:
    """One to three months, on the configured share of accounts."""
    share = float((accounts.statement_gap_months > 0).mean())
    assert abs(share - POPULATION.statement_gap_share) <= 0.02, share
    low, high = POPULATION.statement_gap_length_bounds
    gapped = accounts[accounts.statement_gap_months > 0]
    assert gapped.statement_gap_months.between(low, high - 1).all()
    # and the gap takes the whole statement with it, never half of it
    rows = panel[panel.balance.isna()]
    assert len(rows)
    for column in ("inflow", "txn_count", "min_balance_6m"):
        assert rows[column].isna().all(), column


def test_missingness_is_not_correlated_with_the_label(panel) -> None:
    """MAR, and demonstrably so.

    Beyond the two structural rules — which depend on the borrower's legal form
    and occupation, both of which the model can see — nothing about what is
    missing may carry information about what is going to happen.  A logistic
    regression of the label on the statement-gap flag and the bureau-missing
    flag, controlling for portfolio, must find coefficients indistinguishable
    from zero.

    This is the check that stops a missingness mechanism from becoming a
    covert label: if a gap were more likely on an account about to fail, the
    panel would be handing the model the answer through the back door.
    """
    from sklearn.linear_model import LogisticRegression

    rows = panel[panel.labelable == 1]
    design = pd.DataFrame({
        "statement_gap": rows.balance.isna().astype(float),
        "bureau_missing": rows.bureau_score.isna().astype(float),
    })
    controls = pd.get_dummies(rows.portfolio.astype(str), prefix="pf", dtype=float)
    X = pd.concat([design.reset_index(drop=True), controls.reset_index(drop=True)], axis=1)
    y = rows.default_within_12m.to_numpy()
    # C=inf is the unpenalised fit; scikit-learn 1.8 deprecated penalty=None
    model = LogisticRegression(max_iter=400, C=np.inf).fit(X, y)
    coefficients = dict(zip(X.columns, model.coef_[0]))
    for name in ("statement_gap", "bureau_missing"):
        odds_ratio = float(np.exp(coefficients[name]))
        assert 0.80 <= odds_ratio <= 1.25, (
            f"{name} shifts the odds of default by {odds_ratio:.2f}x — "
            f"the missingness is not missing-at-random"
        )


# --------------------------------------------------------------------------- #
# 5. measurement noise
# --------------------------------------------------------------------------- #
def test_measurement_noise_is_reproducible_under_the_seed() -> None:
    """One seed, one noisy panel — byte for byte, and different across seeds."""
    config = GeneratorConfig(n_accounts=1_200, months=36)
    first, first_accounts = generate(config)
    again, again_accounts = generate(config)
    pd.testing.assert_frame_equal(first, again)
    pd.testing.assert_frame_equal(first_accounts, again_accounts)

    other, _ = generate(GeneratorConfig(n_accounts=1_200, months=36, seed=99))
    assert not first.equals(other)


def test_switching_the_noise_off_changes_only_the_noise() -> None:
    """``noise=False`` is a switch, not a different generator.

    The same accounts, the same portfolios, the same ticket sizes and the same
    NPA months — the latent draw is untouched.  What changes is that nobody is
    silent, nothing is missing, and every instrument reports on time.
    """
    config = GeneratorConfig(n_accounts=2_000, months=36)
    noisy, noisy_accounts = generate(config)
    quiet, quiet_accounts = generate(
        GeneratorConfig(n_accounts=2_000, months=36, noise=False)
    )
    # Who defaults, when, and how risky they looked at origination: identical.
    # `severity` and `onset` are deliberately NOT on this list — a silent
    # defaulter's slide is compressed and floored, which is the whole mechanism.
    fate = ["account_id", "portfolio", "sanctioned_amount", "is_defaulter",
            "npa_month", "risk_z"]
    pd.testing.assert_frame_equal(noisy_accounts[fate], quiet_accounts[fate])
    silent = noisy_accounts.silent_default == 1
    pd.testing.assert_series_equal(
        noisy_accounts.loc[~silent, "severity"], quiet_accounts.loc[~silent, "severity"]
    )
    assert quiet_accounts.silent_default.sum() == 0
    assert quiet_accounts.statement_gap_months.sum() == 0
    assert noisy_accounts.silent_default.sum() > 0
    # with the noise off the shared spine is complete for every row
    assert quiet.balance.notna().all()
    assert quiet.loc[quiet.months_to_npa < 0, "dpd"].max() == 0.0
    assert noisy.loc[noisy.months_to_npa < 0, "dpd"].max() > 0.0


def test_the_gst_return_reaches_the_bank_late(panel, accounts) -> None:
    """A reporting lag, not a rewrite: the turnover series is shifted, not blurred.

    With a lag of one or two months a borrower's *reported* first month repeats
    the value the lender already had, which is what a lender's file actually
    contains at the start of a relationship.
    """
    distribution = sources.value("shared.measurement.gst_report_lag_distribution")
    assert set(distribution) == {0, 1, 2}
    rows = panel[panel.gst_sales.notna() & (panel.month_idx <= 1)]
    repeated = float(
        rows.groupby("account_id", observed=True).gst_sales.nunique().eq(1).mean()
    )
    # An account on a one- or two-month lag has nothing to report for month 0,
    # so the earliest figure it has is held: months 0 and 1 carry the SAME
    # number.  An account filing without a lag shows two different ones.  The
    # share that repeats is therefore P(lag >= 1), read straight off the
    # sourced distribution.
    expected = 1.0 - distribution[0]
    assert abs(repeated - expected) < 0.06, f"{repeated:.3f} vs {expected:.3f}"


def test_demanded_and_collected_are_rounded(panel) -> None:
    """Amounts reach the panel rounded, as they reach a downstream mart."""
    step = sources.value("shared.measurement.amount_rounding_rupees")
    for column in ("demanded_amount", "collected_amount"):
        values = panel[column].dropna().to_numpy(dtype=float)
        assert np.allclose(values % step, 0.0), column


def test_the_collateral_valuation_is_stale(panel, accounts) -> None:
    """A carried collateral value is a step function, not a monthly reading.

    With a refresh cycle of a year, most consecutive months of an LTV series
    move only because the OUTSTANDING moved — so the ratio changes smoothly and
    then jumps when the valuer comes back.  What this asserts is the jump: the
    distribution of month-on-month changes has a long tail that a smoothly
    drifting valuation would not produce.
    """
    rows = panel[panel.ltv.notna()].sort_values(["account_id", "month_idx"])
    change = rows.groupby("account_id").ltv.diff().dropna().abs()
    assert change.quantile(0.99) > 8 * max(change.median(), 1e-6), (
        "no revaluation jumps: the collateral value is being read monthly"
    )


# --------------------------------------------------------------------------- #
# SD-D5 — the labels and the rates
# --------------------------------------------------------------------------- #
def test_the_base_rates_are_inside_their_pre_registered_bands(panel, accounts) -> None:
    """The same assertion the CLI makes on every generated panel.

    Reported as a list rather than raised on the first failure, so a tuning
    round sees every band it broke at once.
    """
    rates = measure_base_rates(panel, accounts)
    problems = assert_base_rates(rates, list(PORTFOLIOS.values()), strict=False)
    assert not problems, "\n".join(problems)


def test_the_sma2_label_means_what_rbi_means(panel) -> None:
    """SMA-2 is 61-90 days past due, read forward six months off the DPD series."""
    rows = panel.sort_values(["account_id", "month_idx"])
    # a hair above the threshold, because the panel's `dpd` is rounded to one
    # decimal AFTER the label is computed, so a true 60.96 arrives as 61.0
    forward = (
        rows.groupby("account_id", observed=True).dpd.shift(-1).ge(SMA2_DPD + 0.1)
        | rows.groupby("account_id", observed=True).dpd.shift(-2).ge(SMA2_DPD + 0.1)
    )
    # every row the shift finds must also be flagged by the generator's label
    # (the generator looks six months forward, and through the post-NPA months
    # the panel does not carry, so it finds strictly more)
    assert rows.loc[forward.fillna(False), "sma2_within_6m"].eq(1).all()
    assert panel.sma2_within_6m.isin({0, 1}).all()


def test_the_sma2_rate_is_plausible_next_to_the_npa_rate(panel, accounts) -> None:
    """A book reaches SMA-2 more often than it reaches NPA, because most cures."""
    rates = measure_base_rates(panel, accounts)
    low, high = sources.value("book.sma2_to_npa_event_ratio_band")
    assert low <= rates.sma2_to_npa_events <= high, (
        f"SMA-2 {rates.sma2:.4f} vs NPA {rates.book:.4f} "
        f"= {rates.sma2_to_npa_events:.2f} entries per NPA per unit time"
    )


def test_the_labels_are_the_last_columns(panel) -> None:
    """Every forward-looking column sits at the end of the panel.

    🔴 ``export_demo.py`` and ``rigor.py`` drop the label columns BY NAME.
    ``sma2_within_6m`` is new and must be added to both ``DROP`` lists; left
    in, it is a forward-looking label served to the model as a feature.
    """
    assert list(panel.columns)[-4:] == [
        "default_within_12m", "sma2_within_6m", "labelable", "months_to_npa",
    ]


# --------------------------------------------------------------------------- #
# the AUC diagnostic — a MEASUREMENT, not a target
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_the_book_is_hard_enough_and_easy_enough() -> None:
    """Grouped AUC lands inside DR-01's band on three seeds, on every portfolio.

    This fits a quick LightGBM on an account-grouped 70/30 split — the same
    diagnostic SD-D2/SD-D3 used to discover that the panel scored 0.97.  It is
    **not** the product model and nothing about it belongs in the generator:
    it is here so that a change to a share or an elasticity cannot quietly
    walk the book out of the band the validation pack pre-registered before
    any model existed.

    The bands are read from ``validation/criteria.yaml``, so this test cannot
    disagree with the criterion it is standing in for.

    Three fits on a million-row panel: this is the slowest thing in the suite
    by a long way, and it is marked ``slow`` for that reason.
    """
    pytest.importorskip("lightgbm")
    from lightgbm import LGBMClassifier
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import roc_auc_score

    low, high = _criterion_threshold("DR-01")
    floor = _criterion_threshold("DR-06")
    categorical = [
        "sector", "region", "loan_type", "segment", "qualification",
        "promoter_age_group", "portfolio", "constitution", "state", "city_tier",
        "nic_group",
    ]
    dropped = [
        "account_id", "month_idx", "date", "default_within_12m", "sma2_within_6m",
        "labelable", "months_to_npa",
    ]
    pooled: list[float] = []
    for seed in (20260709, 11, 4242):
        frame, _ = generate(GeneratorConfig(seed=seed, n_accounts=AUC_ACCOUNTS, months=48))
        for column in categorical:
            frame[column] = frame[column].astype("category")
        y = frame.default_within_12m.to_numpy()
        X = frame.drop(columns=dropped)
        groups = frame.account_id.astype(str).to_numpy()
        train, test = next(
            GroupShuffleSplit(1, test_size=0.30, random_state=7).split(X, y, groups=groups)
        )
        model = LGBMClassifier(
            n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
            colsample_bytree=0.8, min_child_samples=80, random_state=7, n_jobs=-1,
            verbose=-1,
        ).fit(X.iloc[train], y[train], categorical_feature=categorical)
        score = model.predict_proba(X.iloc[test])[:, 1]
        auc = float(roc_auc_score(y[test], score))
        pooled.append(auc)
        assert low <= auc <= high, f"seed {seed}: pooled AUC {auc:.4f} outside [{low}, {high}]"

        held = frame.portfolio.astype(str).to_numpy()[test]
        for code in sorted(set(held)):
            mask = held == code
            if y[test][mask].sum() < 30:
                continue
            per = float(roc_auc_score(y[test][mask], score[mask]))
            assert per >= floor, f"seed {seed}: {code} AUC {per:.4f} below {floor}"
    assert np.std(pooled) < 0.02, f"seed-to-seed spread {np.std(pooled):.4f}: {pooled}"


def _criterion_threshold(criterion_id: str):
    """The pre-registered threshold for one criterion, read from criteria.yaml."""
    import pathlib

    import yaml

    path = pathlib.Path(__file__).resolve().parents[1] / "validation" / "criteria.yaml"
    with path.open() as handle:
        document = yaml.safe_load(handle)
    for criterion in document["criteria"]:
        if criterion["id"] == criterion_id:
            return criterion["threshold"]
    raise KeyError(criterion_id)
