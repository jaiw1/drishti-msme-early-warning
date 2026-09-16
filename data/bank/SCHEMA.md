# `data/bank/` — the bank-enrichment contract (DRISHTi)

What `src/enrich_bank.py` reads from the IDBI Atlas sandbox, what it writes, and what
happens when the sandbox is not available.

```
data/bank/
  raw/                     per-API JSON exactly as Atlas returned it   (gitignored)
  enriched.csv             one row per account, the join of every pull (gitignored)
  provenance.json          per-column source for that enriched.csv     (gitignored)
  provenance.example.json  a committed example of the above            (committed)
  fixture.json             offline stand-in, 160 accounts              (committed)
  check_fixture.py         smoke test for fixture.json                 (committed)
  SCHEMA.md                this file                                   (committed)
```

`enriched.csv` and `provenance.json` are gitignored because they carry sandbox data. The
fixture and this document are committed because four other lanes build against them.

## The fallback rule

```
credentials present AND endpoint approved  ->  live pull      -> column tagged BANK_API
credentials present BUT endpoint pending   ->  fixture column -> column tagged FIXTURE
no credentials / no endpoints at all       ->  whole fixture  -> every column FIXTURE
no bank API supplies this field at all     ->  generator      -> column tagged SIMULATED
```

**The pipeline never fails because the bank is slow.** It degrades to the fixture, records
exactly what happened in `provenance.json`, and the UI badges every value accordingly. A
`FIXTURE` badge on screen is not an embarrassment — it is the disclosure. Silently
presenting simulated data as real is the only outcome that would actually sink this
submission.

`--bank` on `src/export_demo.py` selects the enriched path; without it the pipeline runs
purely synthetic, exactly as it did in July 2026.

## ID spaces

Atlas spells the same identifier four different ways depending on the API. `app/atlas/idmap.py`
in the platform repo normalises all of them; `enriched.csv` uses only the normalised name.

| Space | Atlas spellings | Normalised to | Notes |
|---|---|---|---|
| **CIF** | `custId` · `cifId` · `custCifId` · `customerId` | `cif_id` | The customer. API 402 is keyed by `customerId`. |
| **Account** | `acctId` · `acid` · `foracid` · `accountNo` | `account_no` (+ `foracid` kept verbatim) | The facility. `foracid` is the Finacle form. |
| **AA party** | `vua` -> `consentId` / `linkRefNumber` | not used by DRISHTi | SANKET only. |
| **Employee** | `ein` | `rm_ein` | API 508 HRMS; also API 442 `accountManager`. |

## The 25 APIs — which ones DRISHTi uses, and for what

DRISHTi ingests **15**. The remaining 10 are SANKET's (AA lifecycle, CRM write-back) or
subscribed-unused (415).

| API | What it gives | Keyed by | Feeds these `enriched.csv` columns |
|---|---|---|---|
| **391** | Loan details + restructuring history | account | `portfolio` `product_code` `loan_type` `sanctioned_amount` `disbursed_amount` `outstanding` `sanction_date` `maturity_date` `interest_rate_pa` `tenor_months` `restructured_flag` `restructure_date` `moratorium_end_date` |
| **402** | Overdue details | **CIF** (`customerId`) | `dpd` `npa_status` `npa_date` `asset_classification` |
| **404** | Overdue position (demanded vs collected vs overdue) | account range | `as_on_date` `demanded_amount` `collected_amount` `overdue_amount` `overdue_principal` `overdue_interest` |
| **441** | Drawing power / sanction history | account | `drawing_power` `dp_as_on` `sanction_limit_current` `limit_revision_count` |
| **442** | CIF exposure, rating, account manager | CIF | `cif_total_exposure` `cif_facility_count` `cust_rating` `account_manager_ein` |
| **362** | Liens | account | `lien_count` `lien_amount` `lien_type` |
| **433** | Rates (product-level, **no customer id**) | product | `card_rate_pa` `spread_bps` `product_rate_code` |
| **473** | Repayment schedule (product-level) | product | `emi_amount` `installments_total` `installments_paid` `next_due_date` |
| **538** | Payoff, penal / overdue interest split | account | `payoff_amount` `penal_interest` `foreclosure_charge` |
| **393** | Full statement (cursor paging, 999/page) | account | `credits_3m_avg` `debits_3m_avg` `credit_txn_count_3m` `bounce_count_6m` `cheque_return_count_6m` `min_balance_6m` `avg_balance_3m` |
| **365** | Account enquiry (balances, CIF) | account | `casa_acct_id` `casa_balance` `casa_status` |
| **394** | Accounts by CIF | CIF | `linked_account_count` |
| **456** | Dedupe / master — the **only** place GSTIN appears | CIF / PAN | `gstin` `pan_masked` `customer_count` `dedupe_match_score` `constitution` `entity_name` |
| **408** | CIBIL (bureau permitted for credit monitoring) | CIF | `bureau_score` `bureau_vintage_months` `bureau_enquiries_6m` `bureau_writeoff_flag` `bureau_pulled_on` |
| **508** | HRMS employee | `ein` | `rm_ein` `rm_name` `branch_code` `branch_name` `ifsc` `reporting_manager_ein` |

**Not used by DRISHTi:** 590 · 591 · 592 · 593 · 497 · 498 · 595 · 739 (AA lifecycle, SANKET
only) · 428 (CRM write-back, SANKET only) · 415 (CKYC — subscribed, deliberately not scored on).

### Enumeration

Only API 402 and 404 can be reached without already knowing an account id. **API 404's
`selRangeLoanAcctId` range plus `recCtrlIn.setNum` paging is the most promising enumeration
route** and should be probed before any clarification email. Fall-backs in order: 456
wildcard -> 508 branch list then 394 by CIF -> polite sequential CIF probe. Whatever works
gets recorded in `scratch/browser/probe_results.json`.

### Fields no API supplies — always `SIMULATED`

GST turnover and filing delay · sales trend · adverse remarks and filings · EPFO headcount ·
DISCOM load · utilisation history and inflow trend beyond what 393 reconstructs. These are
generated, and they are the reason the `filings` provenance family exists.

## `enriched.csv`

One row per account, `account_id` as the key. Columns are exactly the fixture's, minus the
`_`-prefixed bookkeeping fields. Grouped by provenance family:

| Family | Columns |
|---|---|
| `identity` | `account_id` `cif_id` `foracid` `account_no` `entity_name` `constitution` `branch_code` `branch_name` `ifsc` `rm_ein` `rm_name` `reporting_manager_ein` `account_manager_ein` `pan_masked` `customer_count` `dedupe_match_score` |
| `exposure` | `portfolio` `product_code` `loan_type` `secured` `sanctioned_amount` `disbursed_amount` `outstanding` `sanction_date` `maturity_date` `interest_rate_pa` `tenor_months` `restructured_flag` `restructure_date` `moratorium_end_date` `drawing_power` `dp_as_on` `sanction_limit_current` `limit_revision_count` `cif_total_exposure` `cif_facility_count` `cust_rating` `lien_count` `lien_amount` `lien_type` `card_rate_pa` `spread_bps` `product_rate_code` `emi_amount` `installments_total` `installments_paid` `next_due_date` `payoff_amount` `penal_interest` `foreclosure_charge` |
| `repayment` | `dpd` `npa_status` `npa_date` `asset_classification` `as_on_date` `demanded_amount` `collected_amount` `overdue_amount` `overdue_principal` `overdue_interest` |
| `cashflow` | `credits_3m_avg` `debits_3m_avg` `credit_txn_count_3m` `bounce_count_6m` `cheque_return_count_6m` `min_balance_6m` `avg_balance_3m` `casa_acct_id` `casa_balance` `casa_status` `linked_account_count` `utilisation` `inflow_vs_6m_avg` |
| `bureau` | `bureau_score` `bureau_vintage_months` `bureau_enquiries_6m` `bureau_writeoff_flag` `bureau_pulled_on` |
| `filings` | `gstin` `gst_turnover_3m` `gst_filing_delay_days` `sales_trend_3m` `adverse_remark_6m` `epfo_headcount` `discom_load_kw` |
| `profile` | `sector` `region` `segment` `promoter_age_group` `business_age_years` `vintage_months` |

Nulls are meaningful and must survive the join: a missing `gstin` says the borrower is an
Individual, a missing `bureau_score` says the bureau had no file. Do not fill them with
zeros — the generator's MAR missingness blocks depend on the distinction.

## `provenance.json`

Written beside `enriched.csv` on every enrichment run. See `provenance.example.json` for a
full instance. Shape:

```jsonc
{
  "provenance_version": 1,
  "product": "drishti",
  "generated_at": "<iso8601>",
  "mode": "live" | "fixture" | "mixed",
  "fixture_reason": "<why anything fell back>",
  "families": { "identity": "BANK_API", ... },          // the 8 families
  "columns":  { "dpd": { "source": "BANK_API", "api_id": "402",
                         "field": "dpd", "pulled_at": "...", "n_records": 1487 }, ... },
  "endpoints": [ { "api_id": "402", "http_status": 200, "n_records": 1487,
                   "subscription_status": "approved", "latency_ms": 288 }, ... ]
}
```

`families` and `endpoints` flow straight into the export's `provenance` and
`meta.sandbox_sync` blocks — see `rrsquad-platform/contracts/drishti_export.schema.json`.
The **`model` family is the weakest of the other seven** in trust order
`BANK_API > SIMULATED > FIXTURE`; the batch runner asserts it.

## `fixture.json`

160 accounts: **20 per portfolio** across all eight (MSME-CC, MSME-TL, Housing, Education,
Agri, Retail-Unsecured, LAP, Auto), 93 columns each, every record tagged
`"_provenance": "FIXTURE"`.

Built to be realistic where realism matters: INR amounts banded per portfolio, IFSC codes on
IDBI's `IBKL` prefix, 9-digit CIFs, Finacle-style `foracid`, 15-character GSTINs with real
state codes, RBI asset classifications consistent with `dpd`, ~30% of accounts under some
stress, ~7% with no bureau file, and no GSTIN on Individual borrowers.

> **Every value in `fixture.json` is fabricated.** No real customer, business, account or
> employee is represented. Names, CIFs, account numbers, GSTINs and PANs are synthetic and
> structurally plausible only.

```bash
python3 data/bank/check_fixture.py     # exits non-zero if the fixture is unusable
```

## Rules

1. **Never commit `raw/`, `enriched.csv` or `provenance.json`.** `.gitignore` covers all
   three; `deploy/verify.sh` greps the built bundles as a second line of defence.
2. **Never put a credential in this directory.** Client ids and secrets live in
   `/etc/rrsquad/*.env` at 0600 and reach the process through systemd `LoadCredential=`.
3. **Every column gets a provenance entry.** A column absent from `provenance.json` must
   fail the enrichment, not default to `BANK_API`.
4. **A pending subscription is disclosed, not hidden.** Pending rows render in the UI.
