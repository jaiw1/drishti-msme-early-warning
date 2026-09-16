"""Smoke test: python3 data/bank/check_fixture.py  -> exits non-zero if the fixture is unusable."""
import json, pathlib
REQUIRED = {"account_id", "cif_id", "portfolio", "constitution", "secured", "sanctioned_amount",
            "dpd", "npa_status", "outstanding", "interest_rate_pa", "branch_code", "rm_ein", "_provenance"}
doc = json.loads((pathlib.Path(__file__).parent / "fixture.json").read_text())
rows = doc["accounts"]
assert rows and doc["_meta"]["mode"] == "fixture", "fixture.json is empty or not marked as a fixture"
assert all(REQUIRED <= set(r) for r in rows), f"missing required keys: {REQUIRED - set(rows[0])}"
assert all(r["_provenance"] == "FIXTURE" for r in rows), "every record must be tagged FIXTURE"
assert len({r["portfolio"] for r in rows}) == 8, "all eight portfolios must be represented"
print(f"OK  {len(rows)} fixture accounts, {len(rows[0])} columns, 8 portfolios, all tagged FIXTURE")
