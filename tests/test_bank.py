"""DM-6: ``src/bank.py`` — the ``--bank`` enrichment path.

``data/bank/SCHEMA.md``'s fallback rule, and the honesty rule beside it (per-account
provenance must never claim more than was actually substituted for THAT account), are
the two things under test here. The real, committed ``data/bank/fixture.json`` is used
directly rather than a synthetic stand-in, so a change to the fixture's own shape (which
this lane does not own) fails a test here before it fails silently downstream.
"""

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bank  # noqa: E402  (path shim must run first)

REPO_DATA = Path(__file__).resolve().parents[1] / "data"
#: real fixture.json covers exactly MSME00001..MSME00160 (see data/bank/SCHEMA.md)
COVERED_ID = "MSME00001"
UNCOVERED_ID = "MSME09999"


# --------------------------------------------------------------------------- #
# weakest() — the trust-order primitive
# --------------------------------------------------------------------------- #
def test_weakest_prefers_fixture_over_simulated_and_bank_api():
    assert bank.weakest(["BANK_API", "SIMULATED", "FIXTURE"]) == "FIXTURE"


def test_weakest_prefers_simulated_over_bank_api():
    assert bank.weakest(["BANK_API", "SIMULATED"]) == "SIMULATED"


def test_weakest_is_bank_api_only_when_nothing_else_present():
    assert bank.weakest(["BANK_API", "BANK_API"]) == "BANK_API"


def test_weakest_of_empty_defaults_simulated():
    assert bank.weakest([]) == "SIMULATED"


# --------------------------------------------------------------------------- #
# --bank not passed: untouched, every family SIMULATED
# --------------------------------------------------------------------------- #
def test_disabled_context_is_all_simulated():
    ctx = bank.build_context(REPO_DATA, enabled=False)
    assert ctx.enabled is False
    assert ctx.mode == "simulated"
    assert set(ctx.families) == set(bank.FAMILIES)
    assert all(v == "SIMULATED" for v in ctx.families.values())


def test_disabled_context_provenance_for_is_all_simulated_for_anyone():
    ctx = bank.build_context(REPO_DATA, enabled=False)
    assert ctx.provenance_for(COVERED_ID) == {f: "SIMULATED" for f in bank.FAMILIES}


def test_disabled_context_never_overlays_anything():
    ctx = bank.build_context(REPO_DATA, enabled=False)
    assert ctx.overlay_for(COVERED_ID) == {}


# --------------------------------------------------------------------------- #
# --bank passed, no pulled.json: whole-fixture fallback (this repo's real state today)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def fixture_ctx(tmp_path_factory):
    """The whole-fixture fallback, isolated from whatever this checkout happens to hold.

    ``data/bank/pulled.json`` is gitignored: absent on a clean clone, present the moment
    the platform's batch runs an enrichment pass here. Reading ``data/`` directly made
    this fixture mean one thing before a pull and another after it, so it builds against
    a directory holding the real, committed ``fixture.json`` and nothing else. The branch
    under test is then the branch named, on any checkout.
    """
    bank_dir = tmp_path_factory.mktemp("fixture-only") / "bank"
    bank_dir.mkdir()
    (bank_dir / bank.FIXTURE_NAME).write_bytes(
        (REPO_DATA / "bank" / bank.FIXTURE_NAME).read_bytes())
    ctx = bank.build_context(bank_dir.parent, enabled=True)
    assert ctx.pulled is None
    return ctx


def test_fixture_fallback_mode_is_fixture(fixture_ctx):
    assert fixture_ctx.mode == "fixture"
    assert fixture_ctx.enabled is True


def test_fixture_fallback_covers_exactly_160_accounts(fixture_ctx):
    assert fixture_ctx.coverage()["fixture_accounts"] == 160


def test_filings_is_always_simulated_even_with_a_live_pull_shape(fixture_ctx):
    """SCHEMA.md: no Atlas API supplies GST turnover / adverse remarks / EPFO / DISCOM."""
    assert fixture_ctx.families["filings"] == "SIMULATED"


def test_the_six_pullable_families_read_fixture_in_whole_fallback_mode(fixture_ctx):
    for fam in ("identity", "exposure", "repayment", "cashflow", "bureau", "profile"):
        assert fixture_ctx.families[fam] == "FIXTURE"


def test_model_family_is_the_weakest_of_the_other_seven(fixture_ctx):
    assert fixture_ctx.families["model"] == bank.weakest(
        [v for k, v in fixture_ctx.families.items() if k != "model"])
    assert fixture_ctx.families["model"] == "FIXTURE"


# --------------------------------------------------------------------------- #
# overlay_for — only identity, only for covered accounts
# --------------------------------------------------------------------------- #
def test_overlay_for_a_covered_account_returns_identity_fields(fixture_ctx):
    overlay = fixture_ctx.overlay_for(COVERED_ID)
    assert overlay, "MSME00001 is fixture account 1 of 160 and must be covered"
    assert set(overlay) <= set(bank.OVERLAY_FIELDS)
    assert overlay.get("rm_ein", "").startswith("EIN-")
    assert overlay["branch_code"]


def test_overlay_for_an_uncovered_account_is_empty(fixture_ctx):
    assert fixture_ctx.overlay_for(UNCOVERED_ID) == {}


def test_overlay_never_carries_a_model_feature(fixture_ctx):
    """dpd/outstanding/sanctioned must never be substituted — see the module docstring:
    the model was trained on the synthetic panel and only the synthetic panel."""
    overlay = fixture_ctx.overlay_for(COVERED_ID)
    for leaky in ("dpd", "outstanding", "sanctioned_amount", "npa_status", "bureau_score"):
        assert leaky not in overlay


# --------------------------------------------------------------------------- #
# provenance_for — honest about partial coverage (the DM-6 headline requirement)
# --------------------------------------------------------------------------- #
def test_covered_account_reads_fixture_for_identity(fixture_ctx):
    prov = fixture_ctx.provenance_for(COVERED_ID)
    assert prov["identity"] == "FIXTURE"


def test_uncovered_account_reads_simulated_for_identity_even_though_the_aggregate_is_fixture(fixture_ctx):
    """The headline honesty requirement: an account outside the fixture's 160 must not
    inherit the run-wide FIXTURE badge for a family nothing was actually overlaid for."""
    prov = fixture_ctx.provenance_for(UNCOVERED_ID)
    assert fixture_ctx.families["identity"] == "FIXTURE"     # the aggregate says FIXTURE
    assert prov["identity"] == "SIMULATED"                   # this account got nothing


def test_non_identity_families_never_read_fixture_per_account(fixture_ctx):
    """Only identity is ever overlaid (module docstring) — the other five pullable
    families must report SIMULATED per account regardless of aggregate coverage,
    because their VALUES are never actually substituted."""
    for account_id in (COVERED_ID, UNCOVERED_ID):
        prov = fixture_ctx.provenance_for(account_id)
        for fam in ("exposure", "repayment", "cashflow", "bureau", "profile"):
            assert prov[fam] == "SIMULATED", f"{account_id}/{fam}"


def test_filings_is_simulated_per_account_too(fixture_ctx):
    for account_id in (COVERED_ID, UNCOVERED_ID):
        assert fixture_ctx.provenance_for(account_id)["filings"] == "SIMULATED"


def test_covered_accounts_model_badge_is_fixture_uncovered_is_simulated(fixture_ctx):
    """`model` = weakest of the other seven, PER ACCOUNT. A covered account has one
    FIXTURE family (identity) among six SIMULATED, so FIXTURE (the worst) wins; an
    uncovered account is SIMULATED everywhere, so SIMULATED wins."""
    assert fixture_ctx.provenance_for(COVERED_ID)["model"] == "FIXTURE"
    assert fixture_ctx.provenance_for(UNCOVERED_ID)["model"] == "SIMULATED"


def test_provenance_for_returns_exactly_the_eight_families(fixture_ctx):
    assert set(fixture_ctx.provenance_for(COVERED_ID)) == set(bank.FAMILIES)


# --------------------------------------------------------------------------- #
# a live pull (pulled.json present): BANK_API beats FIXTURE
# --------------------------------------------------------------------------- #
def _write(path, doc):
    path.write_text(json.dumps(doc))


def test_a_live_pull_that_answers_every_pullable_family_api_still_reads_mixed(tmp_path):
    """`mode == "live"` is structurally UNREACHABLE for DRISHTi: `filings` is
    ALWAYS_SIMULATED (no Atlas API supplies GST turnover / adverse remarks / EPFO
    / DISCOM — SCHEMA.md), so at least one family is always SIMULATED regardless
    of how complete the pull is. This mirrors the platform's own
    `batch/enrich.py::provenance_mode`, which computes mode from ALL non-model
    families including the always-simulated ones — not a bug this module
    introduces. Worth flagging in MODEL_CARD.md's provenance legend.
    """
    bank_dir = tmp_path / "bank"
    bank_dir.mkdir()
    all_apis = set()
    for apis in bank.FAMILY_APIS.values():
        all_apis.update(apis)
    _write(bank_dir / bank.PULLED_NAME, dict(
        apis={a: dict(provenance="BANK_API", http_status=200, n_records=1) for a in all_apis}))
    ctx = bank.build_context(tmp_path, enabled=True)
    assert ctx.mode == "mixed"
    for fam in bank.FAMILY_APIS:
        assert ctx.families[fam] == "BANK_API"
    assert ctx.families["filings"] == "SIMULATED"       # ALWAYS_SIMULATED, live pull or not
    assert ctx.families["model"] == "SIMULATED"          # weakest of (BANK_API*6, SIMULATED)


def test_a_partial_pull_falls_back_to_fixture_for_the_family_that_did_not_answer(tmp_path):
    bank_dir = tmp_path / "bank"
    bank_dir.mkdir()
    # only the bureau family's API (408) answers; everything else must fall back
    _write(bank_dir / bank.PULLED_NAME, dict(apis={"408": dict(provenance="BANK_API")}))
    _write(bank_dir / bank.FIXTURE_NAME, dict(accounts=[dict(account_id="X00001")]))
    ctx = bank.build_context(tmp_path, enabled=True)
    assert ctx.mode == "mixed"
    assert ctx.families["bureau"] == "BANK_API"
    assert ctx.families["identity"] == "FIXTURE"
    assert ctx.families["model"] == "FIXTURE"            # FIXTURE is the weakest present


def test_no_pull_and_no_fixture_degrades_to_fully_simulated(tmp_path):
    ctx = bank.build_context(tmp_path / "nothing-here", enabled=True)
    assert ctx.mode == "simulated"
    assert all(v == "SIMULATED" for v in ctx.families.values())
    assert ctx.overlay_for("anything") == {}
    assert ctx.provenance_for("anything") == {f: "SIMULATED" for f in bank.FAMILIES}


# --------------------------------------------------------------------------- #
# a live pull answering is not the same as it answering about YOU
# --------------------------------------------------------------------------- #
def _pull_naming(account_id: str) -> dict:
    """A pulled.json whose identity API answered, with one record about ``account_id``."""
    return dict(apis={"442": dict(provenance="BANK_API", http_status=200, n_records=1,
                                  records=[dict(customerSummary=dict(acctId=account_id,
                                                                     customerName="SAMPLE"))])})


def test_bank_keys_are_the_ids_the_pull_actually_came_back_with(tmp_path):
    bank_dir = tmp_path / "bank"
    bank_dir.mkdir()
    _write(bank_dir / bank.PULLED_NAME, _pull_naming("SAMPLE-0001"))
    ctx = bank.build_context(tmp_path, enabled=True)
    assert ctx.bank_keys == frozenset({"SAMPLE-0001"})
    assert ctx.fetched_for("SAMPLE-0001") is True
    assert ctx.fetched_for("MSME00001") is False


def test_an_account_the_sandbox_answered_about_reads_bank_api(tmp_path):
    bank_dir = tmp_path / "bank"
    bank_dir.mkdir()
    _write(bank_dir / bank.PULLED_NAME, _pull_naming("SAMPLE-0001"))
    ctx = bank.build_context(tmp_path, enabled=True)
    assert ctx.families["identity"] == "BANK_API"          # the run: the call was answered
    assert ctx.provenance_for("SAMPLE-0001")["identity"] == "BANK_API"


def test_an_account_the_sandbox_never_answered_about_is_not_badged_bank_api(tmp_path):
    """The honesty rule the live enrichment pass forced.

    The sandbox holds a handful of sample accounts. Before this, one answered endpoint
    stamped ``identity: BANK_API`` on every account in the panel — tens of thousands of
    generated rows wearing a bank badge because a call about somebody else came back 200.
    A row is real or it is not, and only the pull's own ids decide which.
    """
    bank_dir = tmp_path / "bank"
    bank_dir.mkdir()
    _write(bank_dir / bank.PULLED_NAME, _pull_naming("SAMPLE-0001"))
    _write(bank_dir / bank.FIXTURE_NAME, dict(accounts=[dict(account_id="X00001",
                                                             cif_id="C1")]))
    ctx = bank.build_context(tmp_path, enabled=True)
    # covered by the fixture, but the bank never answered about it -> FIXTURE, not BANK_API
    assert ctx.provenance_for("X00001")["identity"] == "FIXTURE"
    # neither fetched nor covered -> SIMULATED, exactly as before any pull existed
    assert ctx.provenance_for("MSME44000")["identity"] == "SIMULATED"


def test_the_real_pull_on_this_checkout_badges_no_panel_account_bank_api():
    """Whatever is on this checkout, a panel id must never inherit someone else's 200."""
    ctx = bank.build_context(REPO_DATA, enabled=True)
    for account_id in (COVERED_ID, UNCOVERED_ID, "MSME00160"):
        assert ctx.provenance_for(account_id)["identity"] != "BANK_API"
