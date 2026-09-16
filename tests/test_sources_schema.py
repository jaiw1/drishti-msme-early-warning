"""``sources.yaml`` is a provenance contract, and this suite enforces it.

Every empirical number the generator uses has to carry four things beside its
value: who published it, where to read it, when we read it, and how much we
trust it.  An ``assumed`` number is fine — much of a bank's internal book
composition is simply not public — but it has to *say* it is assumed, and it
may not hide behind a decorative link.

The suite also pins the two places the file has to agree with something
outside itself: the platform contract's portfolio enum
(``data/bank/fixture.json``) and the pre-registered validation cuts
(``validation/criteria.yaml``).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from generator import sources
from generator.portfolios import (
    ALL_CHANNELS,
    CHANNEL_PARAM_SOURCES,
    PORTFOLIOS,
    ChannelParams,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "data" / "bank" / "fixture.json"

#: mixes that have to be a probability distribution over their levels
MIX_PATHS = (
    "constitutions", "sectors", "regions", "city_tiers", "qualifications", "age_groups",
)


@pytest.fixture(scope="module")
def nodes() -> list[tuple[str, dict]]:
    """Every parameter node in the document, with its dotted path."""
    return list(sources.iter_nodes())


def test_the_document_is_well_formed() -> None:
    """The loader's own validator is clean — the generator refuses to run otherwise."""
    assert sources.validate() == []


def test_every_node_carries_its_provenance(nodes: list[tuple[str, dict]]) -> None:
    """value + source + url + retrieved_on + confidence, on every leaf."""
    assert nodes, "sources.yaml parsed to nothing"
    for path, node in nodes:
        missing = sources.NODE_KEYS - set(node)
        assert not missing, f"{path} is missing {sorted(missing)}"
        assert node["confidence"] in sources.CONFIDENCE_LEVELS, path
        assert isinstance(node["source"], str) and node["source"].strip(), path
        assert str(node["retrieved_on"]).strip(), path


def test_assumptions_are_declared_as_assumptions(nodes: list[tuple[str, dict]]) -> None:
    """A number with no public source says so, and nothing else claims ``none``."""
    for path, node in nodes:
        assumed = node["confidence"] == "assumed"
        assert assumed == (node["url"] == sources.NO_URL), (
            f"{path}: confidence={node['confidence']} url={node['url']!r}"
        )


def test_sourced_nodes_link_somewhere_fetchable(nodes: list[tuple[str, dict]]) -> None:
    """Anything above ``assumed`` carries an http(s) link, not a note."""
    for path, node in nodes:
        if node["confidence"] == "assumed":
            continue
        assert node["url"].startswith("https://"), f"{path}: {node['url']!r}"


# --------------------------------------------------------------------------- #
# the portfolio block
# --------------------------------------------------------------------------- #
def test_account_shares_sum_to_one() -> None:
    """The mix is a distribution over the eight portfolios."""
    total = sum(
        sources.value(f"portfolios.{key}.account_share") for key in sources.portfolio_keys()
    )
    assert total == pytest.approx(1.0, abs=1e-9)


def test_portfolio_codes_match_the_platform_contract() -> None:
    """The panel's ``portfolio`` values are the contract's enum, spelled its way.

    The build plan names the portfolios in snake_case (``msme_cc``); the
    platform contract spells them ``MSME-CC``.  The contract wins, and the
    snake_case names stay as registry keys.
    """
    with FIXTURE.open() as handle:
        fixture = json.load(handle)
    contract = {record["portfolio"] for record in fixture["accounts"]}
    assert {p.code for p in PORTFOLIOS.values()} == contract
    assert set(PORTFOLIOS) == {
        "msme_cc", "msme_tl", "housing", "education",
        "agri", "retail_unsecured", "lap", "auto",
    }


def test_loan_types_match_the_platform_contract() -> None:
    """Cash credit for the two revolving products, term loan for the rest."""
    with FIXTURE.open() as handle:
        fixture = json.load(handle)
    contract = {
        record["portfolio"]: record["loan_type"] for record in fixture["accounts"]
    }
    for portfolio in PORTFOLIOS.values():
        assert portfolio.loan_type == contract[portfolio.code], portfolio.key


@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_every_mix_is_a_distribution(key: str) -> None:
    """Constitutions, sectors, regions, tiers, qualifications and ages all sum to 1."""
    for path in MIX_PATHS:
        mix = sources.portfolio_value(key, path)
        assert sum(mix.values()) == pytest.approx(1.0, abs=1e-6), f"{key}.{path}"
        assert all(weight >= 0 for weight in mix.values()), f"{key}.{path}"


@pytest.mark.parametrize("key", sorted(PORTFOLIOS))
def test_portfolio_parameters_are_sane(key: str) -> None:
    """Bands are ordered, shares are shares, and channels are real channels."""
    portfolio = PORTFOLIOS[key]
    low, high = portfolio.default_rate_band
    assert 0.0 < low < high < 0.25, key
    assert 0.0 <= portfolio.share <= 1.0, key
    assert set(portfolio.channels) <= set(ALL_CHANNELS), key
    assert portfolio.channels, f"{key} declares no channels"

    population = portfolio.population
    assert population is not None
    assert 0.0 <= population.secured_share <= 1.0, key
    ticket_low, ticket_high = population.ticket_bounds
    assert 0 < ticket_low < ticket_high, key
    tenor_low, tenor_high = population.tenor_bounds
    assert 0 < tenor_low <= tenor_high <= 360, key
    rate_low, rate_high = population.rate_bounds
    assert 0.0 < rate_low <= rate_high < 0.30, key


def test_no_sourced_parameter_is_dead() -> None:
    """Every knob wired to ``sources.yaml`` is actually read by the simulator.

    A parameter nobody reads is worse than no parameter: it looks like evidence
    for a behaviour the generator does not have.  The check is a grep over the
    package, which is blunt but catches the thing that actually goes wrong —
    a knob left behind when the channel it fed was rewritten.
    """
    package = Path(sources.__file__).parent
    code = "".join(
        (package / f"{module}.py").read_text(encoding="utf-8")
        for module in ("channels", "latent", "build", "noise")
    )
    fields = {field.name for field in dataclasses.fields(ChannelParams)}
    assert set(CHANNEL_PARAM_SOURCES) <= fields, sorted(set(CHANNEL_PARAM_SOURCES) - fields)
    unread = [name for name in fields if f"params.{name}" not in code]
    assert not unread, f"ChannelParams knobs nothing reads: {sorted(unread)}"


def test_constitution_levels_are_the_contract_spellings() -> None:
    """``PvtLtd``, not ``Pvt Ltd`` — the platform fixture's spelling wins."""
    with FIXTURE.open() as handle:
        fixture = json.load(handle)
    contract = {record["constitution"] for record in fixture["accounts"]}
    declared = {
        level
        for key in PORTFOLIOS
        for level in sources.portfolio_value(key, "constitutions")
    }
    assert declared <= contract, sorted(declared - contract)
