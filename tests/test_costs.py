"""DM-5: the asymmetric-cost operating point.

Three things are being defended.

**The optimiser actually finds the optimum.**  On a toy book whose cheapest
threshold can be worked out with a pencil, the search has to land on it — not
near it.  The toy is built so that missing one NPA costs a million rupees and
flagging one healthy account costs one, which is the mandate ("a missed NPA
costs far more than a false positive") in its most extreme form: the answer is
the narrowest cut that leaves no NPA behind.

**A cheaper threshold that breaks a pre-registered criterion is not a
candidate.**  DR-11 is a feasibility filter, not a term in the objective, and
the search must decline the cheaper infeasible pair and say which constraint
level it ended up at.

**Every rupee in the model is labelled.**  A rate lifted from the Atlas sandbox
is ``BANK_API`` with ``sandbox_fixture: true`` — genuine field values from the
bank's contract, not rates observed on our borrowers — and a number that is our
judgement says ``ASSUMPTION`` out loud.  A cost model whose provenance is
unreadable is a cost model nobody can check.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import costs  # noqa: E402  (path shim must run first)


# --------------------------------------------------------------------------- #
# The sandbox capture and its provenance
# --------------------------------------------------------------------------- #
def test_rates_come_from_the_433_capture_and_say_so():
    rates, provenance = costs.load_bank_rates()
    assert rates["effective_rate_pa"] == 12.75
    assert rates["penal_rate_pa"] == 2.0
    for name in ("effective_rate_pa", "penal_rate_pa", "normal_rate_pa"):
        entry = provenance[name]
        assert entry["source"] == costs.BANK_API
        assert entry["api_id"] == "433"
        assert entry["sandbox_fixture"] is True, (
            "the sandbox serves one canned blob to every caller — a rate read from it "
            "must never reach the cockpit unflagged")


def test_the_payoff_rate_is_attributed_to_538_not_433():
    """API 538 is the payoff/penal split; the blob carries both, the tags must not blur."""
    _, provenance = costs.load_bank_rates()
    assert provenance["payoff_interest_rate_pa"]["api_id"] == "538"
    assert provenance["payoff_split"]["api_id"] == "538"


def test_the_538_split_is_reported_unavailable_rather_than_read_as_zero():
    """Every interest component in the canned payoff is "0" because the account is
    standard. Zero is an absence here, and calling it a measurement would put a 0%
    penal loading into the cost model."""
    rates, provenance = costs.load_bank_rates()
    assert rates["payoff_split"]["available"] is False
    assert rates["payoff_split"]["share_penal"] is None
    assert "no split can be read" in provenance["payoff_split"]["note"]


def test_a_live_blob_overrides_the_capture_and_drops_the_sandbox_flag(tmp_path):
    path = tmp_path / "rates.json"
    path.write_text(json.dumps({"rateInfo": {"effectiveRate": "9.25", "penalRate": "3.5"}}))
    rates, provenance = costs.load_bank_rates(path=str(path))
    assert rates["effective_rate_pa"] == 9.25
    assert provenance["effective_rate_pa"]["sandbox_fixture"] is False


def test_a_missing_field_degrades_to_an_assumption_not_to_zero():
    rates, provenance = costs.load_bank_rates(blob={})
    assert rates["effective_rate_pa"] > 0
    assert provenance["effective_rate_pa"]["source"] == costs.ASSUMPTION
    assert provenance["effective_rate_pa"]["confidence"] == "assumed"


def test_every_cost_parameter_carries_a_provenance_entry():
    params, provenance = costs.cost_params()
    for name in params.__dataclass_fields__:
        entry = provenance[name]
        assert entry["source"] in (costs.BANK_API, costs.ASSUMPTION)
        if entry["source"] == costs.ASSUMPTION:
            assert entry["note"], f"{name} is our judgement and must say why"
            assert entry["url"] == "none"
        else:
            assert "sandbox_fixture" in entry


def test_the_two_rate_parameters_are_the_bank_api_ones():
    _, provenance = costs.cost_params()
    for name in costs.RATE_PARAMS:
        assert provenance[name]["source"] == costs.BANK_API
        assert provenance[name]["sandbox_fixture"] is True


# --------------------------------------------------------------------------- #
# Per-account economics
# --------------------------------------------------------------------------- #
def test_lgd_follows_the_panels_own_secured_flag():
    params = costs.CostParams()
    lgd = costs.lgd_vector([1, 0], params)
    assert lgd.tolist() == [params.lgd_secured, params.lgd_unsecured]


def test_an_unknown_secured_flag_is_costed_at_the_midpoint_not_as_secured():
    params = costs.CostParams()
    lgd = costs.lgd_vector([float("nan")], params)
    assert lgd[0] == pytest.approx(0.5 * (params.lgd_secured + params.lgd_unsecured))
    assert lgd[0] > params.lgd_secured, "an unknown must never read as fully secured"


def test_expected_loss_is_principal_at_risk_plus_reversed_income():
    params = costs.CostParams(lgd_secured=0.5, effective_rate_pa=12.0, penal_rate_pa=2.0,
                              income_reversal_months=6.0)
    # 10,00,000 x 0.5  +  10,00,000 x 14% x 0.5 year  =  5,00,000 + 70,000
    assert costs.expected_loss([1_000_000.0], [0.5], params)[0] == pytest.approx(570_000.0)


def test_the_bands_cost_what_the_model_says_they_cost():
    """One good account and one bad one, priced in all three bands by hand."""
    params = costs.CostParams(lgd_unsecured=0.5, effective_rate_pa=10.0, penal_rate_pa=0.0,
                              income_reversal_months=0.0, cure_share_red=0.4,
                              review_cost_red_inr=1_000.0, friction_share_red=0.1)
    ead = np.array([100_000.0, 100_000.0])
    green, _, red = costs.band_costs(ead, [0.0, 1.0], [0.5, 0.5], params)
    assert green.tolist() == [0.0, 50_000.0]                 # only the bad one costs anything
    assert red[0] == pytest.approx(1_000.0 + 0.1 * 10_000.0)  # review + friction on the good one
    assert red[1] == pytest.approx(1_000.0 + 50_000.0 * 0.6)  # review + the loss not cured


# --------------------------------------------------------------------------- #
# The search — does it find the optimum?
# --------------------------------------------------------------------------- #
def _toy(n=1_000, n_bad=50):
    """A book whose cheapest Red threshold can be worked out by hand.

    The ``n_bad`` riskiest accounts all go bad and nobody else does, so the only
    question is where to cut.
    """
    scores = np.arange(n, dtype="float64") / n
    went = np.zeros(n)
    went[-n_bad:] = 1.0                       # the highest-scoring accounts are the bads
    ead = np.full(n, 1_000_000.0)
    secured = np.ones(n)
    portfolio = np.array(["MSME-CC"] * n, dtype=object)
    return scores, went, ead, secured, portfolio


#: a Red flag prevents the loss outright and costs one rupee, so the cheapest cut
#: is the narrowest one that leaves no NPA in Green.
TOY_PARAMS = costs.CostParams(
    lgd_secured=1.0, lgd_unsecured=1.0, income_reversal_months=0.0,
    cure_share_red=1.0, cure_share_amber=0.0,
    review_cost_red_inr=1.0, review_cost_amber_inr=0.0,
    friction_share_red=0.0, friction_share_amber=0.0,
)


def test_the_optimiser_lands_on_the_hand_computed_optimum():
    """Cost alone, with the constraints stood down, must find the pencil answer."""
    scores, went, ead, secured, portfolio = _toy()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio,
                                    params=TOY_PARAMS, sensitivity=False)
    _, ks = costs._cuts(scores)
    # flagging a healthy account costs 1; missing an NPA costs 1,000,000. So the
    # answer is the smallest available cut that still catches all fifty.
    expected = min(int(k) for k in ks if k >= 50)
    assert block["unconstrained"]["bands"]["red"]["n"] == expected
    assert block["unconstrained"]["missed_npa_share"] == 0.0
    assert block["method"] == "cost_minimising"


def test_dr_11_binds_on_the_toy_and_the_price_of_it_is_reported():
    """The cheapest cut puts every NPA in Red, which leaves Amber with a zero bad
    rate — and a zero cannot be strictly above Green's zero. DR-11 therefore
    forces a worse cut, and the block has to say how much worse rather than
    quietly absorbing it."""
    scores, went, ead, secured, portfolio = _toy()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio,
                                    params=TOY_PARAMS, sensitivity=False)
    assert block["chosen"]["bands"]["red"]["defaults"] < 50, (
        "some NPAs must be pushed out of Red for Amber's bad rate to clear Green's")
    assert block["chosen"]["expected_cost"] > block["unconstrained"]["expected_cost"]
    assert block["constraint_cost"] > 0


def test_no_other_candidate_pair_is_cheaper_than_the_one_chosen():
    """The chosen pair beats every feasible pair on the grid, not just its neighbours."""
    scores, went, ead, secured, portfolio = _toy()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio,
                                    params=TOY_PARAMS, sensitivity=False)
    lgd = costs.lgd_vector(secured, TOY_PARAMS)
    grid = costs._search(scores, went, costs.band_costs(ead, went, lgd, TOY_PARAMS), portfolio)
    cheapest = float(np.min(np.where(grid["levels"][block["constraint_level"]],
                                     grid["total"], np.inf)))
    assert block["chosen"]["expected_cost"] == pytest.approx(cheapest, rel=1e-9)


def test_a_review_that_costs_more_than_the_loss_collapses_the_red_band():
    """The asymmetry, read the other way: when a review costs more than the loss it
    prevents, flagging stops being worth it and the band shrinks to nothing."""
    scores, went, ead, secured, portfolio = _toy()
    wide = costs.choose_thresholds(scores, went, ead, secured, portfolio,
                                   params=TOY_PARAMS, sensitivity=False)
    timid = costs.choose_thresholds(
        scores, went, ead, secured, portfolio, sensitivity=False,
        params=costs.replace(TOY_PARAMS, review_cost_red_inr=1_500_000.0))
    assert (timid["unconstrained"]["bands"]["red"]["n"]
            < wide["unconstrained"]["bands"]["red"]["n"])


# --------------------------------------------------------------------------- #
# The constraints
# --------------------------------------------------------------------------- #
def _graded(n_per=400, portfolios=("MSME-CC", "Housing", "Agri")):
    """A book where the bad rate rises with the score inside every portfolio.

    Built so that band monotonicity is achievable but not automatic: a cut that
    leaves a portfolio's Amber band empty still fails it.
    """
    rng = np.random.default_rng(3)
    scores, went, codes = [], [], []
    for code in portfolios:
        s = rng.uniform(0, 1, n_per)
        scores.append(s)
        went.append((rng.uniform(0, 1, n_per) < s ** 3).astype("float64"))
        codes.append(np.array([code] * n_per, dtype=object))
    scores = np.concatenate(scores)
    went = np.concatenate(went)
    codes = np.concatenate(codes)
    return scores, went, np.full(scores.size, 500_000.0), np.ones(scores.size), codes


def _band_rates(scores, went, amber, red):
    """Green / Amber / Red realised bad rates, by the gate's own arithmetic."""
    red_mask = scores >= red
    amber_mask = (scores >= amber) & ~red_mask
    green_mask = ~red_mask & ~amber_mask
    return [float(went[m].sum()) / len(went[m]) if m.any() else 0.0
            for m in (green_mask, amber_mask, red_mask)]


def test_the_chosen_pair_satisfies_the_constraint_level_it_claims():
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    assert block["constraint_level"] in ("all_pre_registered", "portfolio_monotone_only")
    for code in set(portfolio.tolist()):
        m = portfolio == code
        rates = _band_rates(scores[m], went[m], block["amber"], block["red"])
        assert rates[0] < rates[1] < rates[2], f"{code} is not monotone: {rates}"


def test_red_is_non_empty_in_every_portfolio_at_the_strictest_level():
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    if block["constraint_level"] != "all_pre_registered":
        pytest.skip("this book could not satisfy the strictest level")
    for code in set(portfolio.tolist()):
        m = portfolio == code
        assert int((scores[m] >= block["red"]).sum()) >= 1


def test_a_cheaper_pair_that_breaks_dr_11_is_declined():
    """Cost is the objective; the pre-registered criterion is a filter over it."""
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    free = block["unconstrained"]
    assert free is not None
    assert block["chosen"]["expected_cost"] >= free["expected_cost"]
    assert block["constraint_cost"] == pytest.approx(
        block["chosen"]["expected_cost"] - free["expected_cost"])


def test_the_ladder_records_how_many_pairs_each_level_admits():
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    counts = [row["n_feasible"] for row in block["constraints"]["ladder"]]
    assert counts == sorted(counts), "a looser level cannot admit fewer pairs than a stricter one"
    assert block["constraints"]["applied"] == block["constraint_level"]


def test_the_objective_never_mentions_auc_or_a_validation_band():
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    assert "auc" not in block["objective"].lower()
    assert "FEASIBILITY FILTERS ONLY" in block["constraints"]["note"]


# --------------------------------------------------------------------------- #
# Degrading, and the shape the contract consumes
# --------------------------------------------------------------------------- #
def test_a_book_too_thin_to_band_degrades_to_the_current_pair():
    block = costs.choose_thresholds(
        np.array([0.5]), np.array([1.0]), np.array([1e6]), np.array([1.0]),
        np.array(["Agri"], dtype=object), current=(0.04, 0.40), sensitivity=False)
    assert block["feasible"] is False
    assert (block["amber"], block["red"]) == (0.04, 0.40)


def test_the_block_is_json_and_carries_what_the_platform_needs():
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio)
    text = json.dumps(block, allow_nan=False)          # no numpy scalars, no NaN
    reloaded = json.loads(text)
    assert reloaded["method"] == "cost_minimising"
    assert reloaded["override"]["table"] == "threshold_change"
    assert reloaded["override"]["api"] == "PUT /drishti/threshold"
    assert reloaded["alternatives"] and all(
        {"amber", "red", "expected_cost"} <= set(a) for a in reloaded["alternatives"])
    assert reloaded["cost_curve"]["red_sweep"] and reloaded["cost_curve"]["amber_sweep"]
    assert reloaded["sensitivity"], "the most uncertain parameters must be swept and reported"
    assert all(math.isfinite(row["expected_cost"]) for row in reloaded["alternatives"])


def test_alternatives_are_sorted_by_cost_and_distinct():
    scores, went, ead, secured, portfolio = _graded()
    alts = costs.choose_thresholds(scores, went, ead, secured, portfolio,
                                   sensitivity=False)["alternatives"]
    assert [a["expected_cost"] for a in alts] == sorted(a["expected_cost"] for a in alts)
    assert len({(a["amber"], a["red"]) for a in alts}) == len(alts)


def test_thresholds_are_quantised_before_they_are_costed():
    """The pair the search prices must be the pair the export applies, bit for bit."""
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    for key in ("amber", "red"):
        assert round(block[key], costs.THRESHOLD_DECIMALS) == block[key]
    assert block["chosen"]["bands"]["red"]["n"] == int((scores >= block["red"]).sum())


def test_per_portfolio_lgd_is_reported_against_the_sourced_secured_share():
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    by_code = {row["portfolio"]: row for row in block["by_portfolio"]}
    assert set(by_code) == set(portfolio.tolist())
    for row in by_code.values():
        assert 0.0 <= row["secured_share_observed"] <= 1.0
        # sources.yaml is a cross-check, so it may legitimately be absent
        assert row["secured_share_sources_yaml"] is None or 0.0 <= row["secured_share_sources_yaml"] <= 1.0


def test_a_renamed_sources_node_degrades_the_report_not_the_model(monkeypatch):
    monkeypatch.setattr(costs, "_KEY_BY_CODE", {})
    assert costs.declared_secured_share("MSME-CC") is None


def test_an_inadmissible_pair_is_labelled_so_a_cheaper_cost_cannot_mislead():
    """The July pair can price out cheaper than the chosen one precisely because it
    is not a legal pair. Without the label the block would read as a lost race."""
    scores, went, ead, secured, portfolio = _toy()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio,
                                    params=TOY_PARAMS, sensitivity=False)
    assert block["chosen"]["constraint_level"] == block["constraint_level"]
    assert block["unconstrained"]["constraint_level"] != "all_pre_registered"
    if block["delta"]["expected_cost"] < 0:
        assert block["current"]["constraint_level"] != "all_pre_registered"
        assert "not admissible" in block["delta"]["note"]


def test_feasibility_level_agrees_with_the_search_grid():
    """Two implementations decide admissibility — the vectorised grid and the
    per-pair check. They must never disagree about the pair that was chosen."""
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    assert costs._feasibility_level(scores, went, portfolio,
                                    block["amber"], block["red"]) == block["constraint_level"]


def test_a_pair_that_cannot_band_the_book_has_no_level():
    scores = np.linspace(0, 1, 100)
    went = np.zeros(100)
    portfolio = np.array(["Agri"] * 100, dtype=object)
    assert costs._feasibility_level(scores, went, portfolio, 0.9, 0.95) is not None
    assert costs._feasibility_level(scores, went, portfolio, 1.5, 1.6) is None


def test_the_cost_curve_carries_the_trade_off_in_counts_not_only_rupees():
    """A cost curve alone tells an officer nothing about what a move does to his queue."""
    scores, went, ead, secured, portfolio = _graded()
    curve = costs.choose_thresholds(scores, went, ead, secured, portfolio,
                                    sensitivity=False)["cost_curve"]
    reds = curve["red_sweep"]
    assert all({"red", "expected_cost", "n_red", "npas_in_red", "npas_not_in_red",
                "false_positives"} <= set(p) for p in reds)
    # a lower Red cut-off catches more of them and reviews more healthy accounts
    ordered = sorted(reds, key=lambda p: p["red"])
    assert ordered[0]["npas_in_red"] >= ordered[-1]["npas_in_red"]
    assert ordered[0]["false_positives"] >= ordered[-1]["false_positives"]
    for point in reds:
        assert point["n_red"] == point["npas_in_red"] + point["false_positives"]


def test_the_curve_does_not_confuse_not_in_red_with_left_in_green():
    """Two different quantities with two different names, deliberately."""
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    at_chosen = min(block["cost_curve"]["red_sweep"],
                    key=lambda p: abs(p["red"] - block["red"]))
    left_in_green = block["chosen"]["missed_npa_share"] * block["chosen"]["n_defaulted"]
    assert at_chosen["npas_not_in_red"] >= left_in_green, (
        "NPAs outside Red must include the ones in Amber as well as the ones in Green")


def test_provenance_is_emitted_both_structured_and_readable():
    scores, went, ead, secured, portfolio = _graded()
    block = costs.choose_thresholds(scores, went, ead, secured, portfolio, sensitivity=False)
    summary = block["provenance_summary"]
    assert block["currency"] == "INR"
    assert set(summary) == {k for k in block["provenance"] if not k.startswith("_")}
    assert all(isinstance(v, str) for v in summary.values())
    assert "sandbox fixture" in summary["effective_rate_pa"]
    assert summary["lgd_unsecured"].startswith(costs.ASSUMPTION)
