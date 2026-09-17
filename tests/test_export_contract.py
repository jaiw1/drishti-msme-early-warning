"""DM-6: ``src/export_contract.py`` — the platform-contract-shaped ``--out`` export.

Four things are under test, matching the DM-6 brief exactly: the ``meta`` envelope
(exactly the keys the contract declares, none of ``export_demo``'s own extras),
provenance precedence (``--bank`` on vs off, covered vs uncovered account), demo-sample
stratification (size, full-panel metrics untouched, spotlight preserved), and strict
JSON (the contract export dumps with ``allow_nan=False`` and round-trips).

A fifth test shells out to the platform's own ``contracts/validate.py`` and asserts the
emitted export reports 0 errors OR only the one DOCUMENTED gap (``rank_order.by_portfolio``
kept as an array — see ``export_contract.py``'s module docstring and BE-7's finding). It
skips gracefully when the sibling ``rrsquad-platform`` checkout is not present, since this
repo does not depend on that one existing to run its own suite.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bank  # noqa: E402  (path shim must run first)
import export_contract  # noqa: E402
import export_demo  # noqa: E402
from generator import GeneratorConfig, generate  # noqa: E402

ROOT = Path(export_demo.ROOT)
REPO_DATA = ROOT / "data"
PLATFORM_VALIDATE = ROOT.parent / "rrsquad-platform" / "contracts" / "validate.py"

#: small enough to train in a few seconds; wide enough every portfolio appears at REF_MONTH
CONTRACT_ACCOUNTS = 1_400
CONTRACT_MONTHS = 28


@pytest.fixture(scope="module")
def internal_payload():
    """The real export payload, built end to end, WITH the bootstrap stats sink filled."""
    panel, accounts = generate(GeneratorConfig(n_accounts=CONTRACT_ACCOUNTS, months=CONTRACT_MONTHS))
    panel = panel.assign(account_id=panel.account_id.astype(str))
    static = accounts.assign(account_id=accounts.account_id.astype(str)).set_index("account_id")
    sink = {}
    out = export_demo.build_export(panel, static, stats_sink=sink)
    return out, sink


@pytest.fixture(scope="module")
def contract_no_bank(internal_payload):
    out, sink = internal_payload
    export, debug = export_contract.build_contract_export(
        out, label="test-no-bank", seed=7, bank_ctx=None, root=ROOT, bootstrap_data=sink)
    return export, debug


@pytest.fixture(scope="module")
def fixture_bank_ctx(tmp_path_factory):
    """The whole-fixture fallback, isolated from whatever this checkout happens to hold.

    ``data/bank/pulled.json`` is gitignored: absent on a clean clone, present the moment the
    platform's batch runs an enrichment pass here. These tests are about what ``--bank`` does
    with the committed fixture, so they build against a directory holding that fixture and
    nothing else, and mean the same thing on either kind of checkout.
    """
    bank_dir = tmp_path_factory.mktemp("fixture-only") / "bank"
    bank_dir.mkdir()
    (bank_dir / bank.FIXTURE_NAME).write_bytes(
        (REPO_DATA / "bank" / bank.FIXTURE_NAME).read_bytes())
    ctx = bank.build_context(bank_dir.parent, enabled=True)
    assert ctx.pulled is None
    return ctx


@pytest.fixture(scope="module")
def contract_with_bank(internal_payload, fixture_bank_ctx):
    out, sink = internal_payload
    export, debug = export_contract.build_contract_export(
        out, label="test-with-bank", seed=11, bank_ctx=fixture_bank_ctx, root=ROOT,
        bootstrap_data=sink)
    return export, debug


# --------------------------------------------------------------------------- #
# the meta envelope
# --------------------------------------------------------------------------- #
CONTRACT_META_KEYS = {
    "product", "schema_version", "model_run_id", "generated_at", "git_sha", "seed",
    "criteria_sha", "provenance_version", "sandbox_sync", "generated_from",
    "reference_month", "horizon_months", "npa_definition_dpd", "n_accounts_scored",
}


def test_meta_has_exactly_the_contract_keys_no_internal_extras(contract_no_bank):
    """`export_demo`'s own `meta` carries `channels`/`channels_by_portfolio`, which the
    contract's `meta` schema does not declare (`additionalProperties: false` there) —
    this must be a FRESH dict, not the internal one reused."""
    meta = contract_no_bank[0]["meta"]
    assert set(meta) == CONTRACT_META_KEYS


def test_meta_product_and_schema_version(contract_no_bank):
    meta = contract_no_bank[0]["meta"]
    assert meta["product"] == "drishti"
    assert meta["schema_version"] == export_contract.SCHEMA_VERSION


def test_model_run_id_is_a_deterministic_function_of_label():
    a = export_contract.model_run_id("same-label")
    b = export_contract.model_run_id("same-label")
    c = export_contract.model_run_id("different-label")
    assert a == b, "a re-run with the same --label must mint the same model_run_id"
    assert a != c


def test_model_run_id_is_a_valid_uuid_shape():
    import uuid

    run_id = export_contract.model_run_id("shape-check")
    assert str(uuid.UUID(run_id)) == run_id


def test_git_sha_is_real_forty_hex_chars(contract_no_bank):
    sha = contract_no_bank[0]["meta"]["git_sha"]
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)
    assert sha != "0" * 40, "this repo IS a git checkout — expected a real sha, not the placeholder"


def test_criteria_sha_matches_the_committed_criteria_yaml(contract_no_bank):
    import hashlib

    expected = hashlib.sha256((ROOT / "validation" / "criteria.yaml").read_bytes()).hexdigest()
    assert contract_no_bank[0]["meta"]["criteria_sha"] == expected


def test_sandbox_sync_mode_is_fixture_with_no_endpoints_when_bank_disabled(contract_no_bank):
    sync = contract_no_bank[0]["meta"]["sandbox_sync"]
    assert sync["mode"] == "fixture"
    assert sync["endpoints"] == []       # schema: MUST be empty in fixture mode


def test_sandbox_sync_mode_is_fixture_with_no_endpoints_on_whole_fixture_fallback(contract_with_bank):
    """Still `fixture` mode (no live pulled.json exists in this checkout), but the
    reason and coverage differ from the disabled case — see the bank tests."""
    sync = contract_with_bank[0]["meta"]["sandbox_sync"]
    assert sync["mode"] == "fixture"
    assert sync["endpoints"] == []


def test_generated_from_names_the_enrichment_only_when_bank_is_on(contract_no_bank, contract_with_bank):
    assert "IDBI Atlas sandbox" not in contract_no_bank[0]["meta"]["generated_from"]
    assert "IDBI Atlas sandbox" in contract_with_bank[0]["meta"]["generated_from"]


# --------------------------------------------------------------------------- #
# provenance precedence — --bank off vs on, covered vs uncovered account
# --------------------------------------------------------------------------- #
def test_without_bank_every_account_is_simulated_in_all_eight_families(contract_no_bank):
    export = contract_no_bank[0]
    assert export["accounts"], "fixture produced no accounts to check"
    for account in export["accounts"]:
        assert account["provenance"] == {f: "SIMULATED" for f in bank.FAMILIES}


def test_without_bank_no_account_carries_a_bank_identity_field(contract_no_bank):
    for account in contract_no_bank[0]["accounts"]:
        for field in bank.OVERLAY_FIELDS:
            if field == "cif_id":
                continue          # cif_id always gets the synthetic fallback — see below
            assert field not in account


def test_without_bank_cif_id_is_the_deterministic_synthetic_fallback(contract_no_bank):
    for account in contract_no_bank[0]["accounts"][:20]:
        assert account["cif_id"] == export_contract._synthetic_cif_id(account["account_id"])
        assert account["cif_id"].startswith("9")


def test_with_bank_a_covered_account_gets_real_fixture_identity(contract_with_bank, fixture_bank_ctx):
    by_id = {a["account_id"]: a for a in contract_with_bank[0]["accounts"]}
    covered = [aid for aid in by_id if aid in fixture_bank_ctx.fixture_by_account]
    assert covered, "expected at least one held-out account inside the fixture's MSME00001-160 range"
    account = by_id[covered[0]]
    fixture_row = fixture_bank_ctx.fixture_by_account[covered[0]]
    assert account["provenance"]["identity"] == "FIXTURE"
    assert account["cif_id"] == fixture_row["cif_id"]
    assert account.get("rm_ein") == fixture_row["rm_ein"]


def test_with_bank_an_uncovered_account_stays_simulated_and_synthetic(contract_with_bank, fixture_bank_ctx):
    by_id = {a["account_id"]: a for a in contract_with_bank[0]["accounts"]}
    uncovered = [aid for aid in by_id if aid not in fixture_bank_ctx.fixture_by_account]
    assert uncovered
    account = by_id[uncovered[0]]
    assert account["provenance"]["identity"] == "SIMULATED"
    assert account["cif_id"] == export_contract._synthetic_cif_id(account["account_id"])
    assert "rm_ein" not in account


def test_with_bank_no_account_ever_gets_a_repayment_or_exposure_value_substituted(contract_with_bank):
    """The module's central honesty rule: dpd/outstanding/sanctioned always come from
    the synthetic panel — the model was never trained on anything else."""
    for account in contract_with_bank[0]["accounts"]:
        assert account["provenance"]["repayment"] == "SIMULATED"
        assert account["provenance"]["exposure"] == "SIMULATED"
        assert account["provenance"]["filings"] == "SIMULATED"


# --------------------------------------------------------------------------- #
# strict JSON
# --------------------------------------------------------------------------- #
def test_contract_export_is_strict_json(contract_no_bank, contract_with_bank):
    for export, _ in (contract_no_bank, contract_with_bank):
        text = json.dumps(export, allow_nan=False)       # raises on any NaN/Infinity
        assert json.loads(text) == export


def test_no_nan_or_infinity_string_anywhere(contract_with_bank):
    text = json.dumps(contract_with_bank[0])
    assert "NaN" not in text and "Infinity" not in text


# --------------------------------------------------------------------------- #
# runway_estimate — ported from app/src/lib/runway.js
# --------------------------------------------------------------------------- #
def test_runway_estimate_none_on_short_history():
    tl = [dict(date=f"2024-{m:02d}", pd=0.1, pd_smooth=0.1) for m in range(1, 4)]
    assert export_contract.runway_estimate(tl, "2024-03", 0.4) is None


def test_runway_estimate_none_when_flat():
    tl = [dict(date=f"2024-{m:02d}", pd=0.05, pd_smooth=0.05) for m in range(1, 8)]
    assert export_contract.runway_estimate(tl, "2024-07", 0.4) is None


def test_runway_estimate_projects_months_to_the_red_threshold():
    # needs >=7 months of history (JS parity); only the last 6 feed the fit
    vals = [0.02, 0.05, 0.08, 0.11, 0.14, 0.17, 0.20]     # rising 0.03/month, cur=0.20
    tl = [dict(date=f"2024-{m:02d}", pd=v, pd_smooth=v) for m, v in enumerate(vals, start=1)]
    months = export_contract.runway_estimate(tl, "2024-07", 0.4)
    assert months is not None
    # target 0.4, cur 0.20, slope ~0.03/mo -> ceil(0.2/0.03) = 7, clamped to [1, 12]
    assert 1 <= months <= 12


def test_runway_estimate_is_capped_at_twelve_months():
    vals = [0.01, 0.011, 0.012, 0.013, 0.014, 0.0141]
    tl = [dict(date=f"2024-{m:02d}", pd=v, pd_smooth=v) for m, v in enumerate(vals, start=1)]
    months = export_contract.runway_estimate(tl, "2024-06", 0.9)
    assert months is None or months <= 12


# --------------------------------------------------------------------------- #
# bootstrap_auc_ci
# --------------------------------------------------------------------------- #
def test_bootstrap_auc_ci_shape(internal_payload):
    _, sink = internal_payload
    ci = export_contract.bootstrap_auc_ci(sink["account_id"], sink["y"], sink["p"], value=0.9, n_boot=20)
    assert set(ci) == {"value", "ci_low", "ci_high", "n", "method"}
    assert ci["method"] == "bootstrap"
    assert 0.0 <= ci["ci_low"] <= ci["value"] <= ci["ci_high"] <= 1.0 or ci["ci_low"] <= ci["value"]
    assert ci["n"] > 0


def test_bootstrap_auc_ci_value_is_the_published_auc_not_recomputed(internal_payload):
    """The point estimate must be exactly what every other report cites — the
    bootstrap only brackets it, never replaces it."""
    _, sink = internal_payload
    ci = export_contract.bootstrap_auc_ci(sink["account_id"], sink["y"], sink["p"], value=0.777, n_boot=10)
    assert ci["value"] == 0.777


# --------------------------------------------------------------------------- #
# cost_model_block — degrades to a >=2-point curve even from a thin/empty grid
# --------------------------------------------------------------------------- #
def test_cost_model_block_curve_has_at_least_two_points_from_a_real_run(internal_payload):
    out, _ = internal_payload
    block = export_contract.cost_model_block(out["thresholds"])
    assert len(block["curve"]) >= 2
    assert block["cost_missed_npa"] > 0
    assert block["cost_false_positive"] > 0
    assert block["provenance"] == {"rates": "BANK_API", "costs": "SIMULATED"}


def test_cost_model_block_degrades_gracefully_from_an_empty_grid():
    """A book too thin to search at all (`_search` returned `None`, so `cost_curve`'s
    sweeps are empty and only `chosen`/`current` exist) must still produce a
    schema-valid >=2-point curve, never crash and never fabricate a third number."""
    thin = dict(
        red=0.4, amber=0.04,
        cost_params=dict(effective_rate_pa=12.75, penal_rate_pa=2.0,
                         review_cost_red_inr=18000.0, friction_share_red=0.15,
                         lgd_secured=0.4),
        by_portfolio=[dict(portfolio="Auto", n=10, expected_loss_mean_inr=500000.0,
                           ead_mean_inr=2000000.0, lgd_mean=0.4)],
        cost_curve=dict(red_sweep=[], amber_sweep=[]),
        chosen=dict(red=0.4, expected_cost=1000.0,
                   bands=dict(red=dict(n=2, defaults=1), amber=dict(n=3, defaults=0),
                             green=dict(n=5, defaults=0))),
        current=dict(red=0.4, expected_cost=1200.0,
                    bands=dict(red=dict(n=1, defaults=1), amber=dict(n=2, defaults=0),
                              green=dict(n=7, defaults=0))),
    )
    block = export_contract.cost_model_block(thin)
    assert len(block["curve"]) >= 2
    for point in block["curve"]:
        assert point["expected_cost"] >= 0
        assert point["n_flagged"] >= 0


# --------------------------------------------------------------------------- #
# --demo-sample stratification
# --------------------------------------------------------------------------- #
def test_demo_sample_returns_roughly_the_requested_size(internal_payload):
    out, _ = internal_payload
    n = 200
    demo = export_contract.stratified_sample(out, n, seed=7)
    # largest-remainder allocation + forced spotlight inclusion can overshoot slightly,
    # never by much on a book this size
    assert abs(len(demo["portfolio"]) - n) <= max(20, len(out.get("spotlight", [])))


def test_demo_sample_keeps_full_panel_metrics_untouched(internal_payload):
    out, _ = internal_payload
    demo = export_contract.stratified_sample(out, 100, seed=7)
    assert demo["metrics"] == out["metrics"]
    assert demo["thresholds"] == out["thresholds"]
    assert demo["portfolio_summary"] == out["portfolio_summary"]
    assert demo["rigor"] == out["rigor"]
    assert demo["ecosystem"] == out["ecosystem"]


def test_demo_sample_timelines_match_the_sampled_accounts_exactly(internal_payload):
    out, _ = internal_payload
    demo = export_contract.stratified_sample(out, 150, seed=7)
    sampled_ids = {r["account_id"] for r in demo["portfolio"]}
    assert set(demo["timelines"]) == sampled_ids


def test_demo_sample_never_drops_a_spotlight_account(internal_payload):
    out, _ = internal_payload
    demo = export_contract.stratified_sample(out, 50, seed=7)
    sampled_ids = {r["account_id"] for r in demo["portfolio"]}
    assert set(out["spotlight"]) <= sampled_ids


def test_demo_sample_covers_every_portfolio_the_full_panel_has(internal_payload):
    out, _ = internal_payload
    demo = export_contract.stratified_sample(out, 300, seed=7)
    full_portfolios = {r["portfolio"] for r in out["portfolio"]}
    sampled_portfolios = {r["portfolio"] for r in demo["portfolio"]}
    assert sampled_portfolios == full_portfolios


def test_demo_sample_n_zero_or_over_full_size_returns_everything(internal_payload):
    out, _ = internal_payload
    demo = export_contract.stratified_sample(out, 0, seed=7)
    assert len(demo["portfolio"]) == len(out["portfolio"])
    demo2 = export_contract.stratified_sample(out, 10**9, seed=7)
    assert len(demo2["portfolio"]) == len(out["portfolio"])


def test_demo_sample_is_reproducible_for_the_same_seed(internal_payload):
    out, _ = internal_payload
    a = export_contract.stratified_sample(out, 120, seed=42)
    b = export_contract.stratified_sample(out, 120, seed=42)
    assert {r["account_id"] for r in a["portfolio"]} == {r["account_id"] for r in b["portfolio"]}


def test_demo_sample_json_is_strict(internal_payload):
    out, _ = internal_payload
    demo = export_contract.stratified_sample(out, 80, seed=7)
    text = json.dumps(demo, allow_nan=False)
    assert json.loads(text) == demo


# --------------------------------------------------------------------------- #
# validate.py — 0 errors, or only the documented rank_order.by_portfolio gap
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not PLATFORM_VALIDATE.exists(),
                    reason="sibling ../rrsquad-platform checkout not present")
def test_validate_py_reports_only_the_documented_gap(contract_with_bank, tmp_path):
    export = contract_with_bank[0]
    out_path = tmp_path / "drishti_export.json"
    out_path.write_text(json.dumps(export, allow_nan=False))

    result = subprocess.run(
        [sys.executable, str(PLATFORM_VALIDATE), "drishti", str(out_path)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    stdout = result.stdout
    if result.returncode == 0:
        assert "VALID" in stdout
        return
    # otherwise: exactly one documented gap, and nothing else
    assert stdout.count("\n  ") <= 2 or "(1 error)" in stdout, stdout
    assert "rank_order.by_portfolio" in stdout, stdout
    assert "is not of type 'object'" in stdout, stdout
