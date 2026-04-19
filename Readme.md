# Stripe DATEV Exporter

Local custom changes and operational defaults are tracked in `LOCAL_CHANGELOG.md`.

## Requirements

- Tested on Python 3.9 - 3.12
- Dependencies listed in `pyproject.toml` (uv) and `requirements.txt` (pip)

## Environment

Consider using [uv](https://docs.astral.sh/uv/) or Python's [virtualenv](https://pypi.org/project/virtualenv/) or alternatives.

When using uv, in the commands below replace `python stripe-datev-cli.py` with `uv run stripe-datev-cli.py`.

## How to Use

```
python stripe-datev-cli.py fill_account_numbers
```

Run this before `download`. This assigns the `accountNumber` metadata to each customer, this will be the account number for all booking records related to this customer. You can assign the `accountNumber` metadata using a different approach, if you like, but every customer (which has any transactions) needs this metadata.

```
python stripe-datev-cli.py list_accounts
python stripe-datev-cli.py list_accounts <file>
```

Outputs a CSV file with all customers, suitable to import into DATEV as master data (Stammdaten). Skip the output file argument to output to stdout. Otherwise, the file is written in Latin1 encoding.

```
python stripe-datev-cli.py download <year> <month>
python stripe-datev-cli.py download <year> <month> --pdf-workers 23 --pdf-max-rps 23
python stripe-datev-cli.py download <year> <month> --include-historical-warnings
```

Processes all invoices, charges and transactions in the given month, and writes all artifacts into one month folder.

New output layout per monthly run:

- `./out/<YYYY>/Q<1-4>/datev/` — **all EXTF CSVs for the whole quarter** (accountant's single import folder)
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/overview/`
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/monthly_recognition/`
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/files/invoices/` — Stripe invoice PDFs (GoBD-relevant)
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/files/receipts/` — Stripe payment receipts (HTML, optional, skip via `--skip-receipts`)
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/logs/download-YYYYMMDD-HHMMSS.log` (auto-generated per run, written live during execution — captures stdout/stderr including Info/Warning lines and counts)

Rationale for quarter-level `datev/`: an accountant imports one folder per DATEV-Buchungsperiode. With three monthly EXTF files per quarter sitting next to each other (`EXTF_YYYY-01_Revenue.csv`, `EXTF_YYYY-01_Balance.csv`, `EXTF_YYYY-02_…`), they select the quarter folder once and DATEV picks them all up.

Legacy locations still recognised for re-runs on older months:
- pre-2026-04: combined `./out/.../<YYYY-MM>/pdf/` folder
- 2026-04 transition: flat `./out/.../<YYYY-MM>/invoices/` + `receipts/` (before `files/` nesting)
- pre-quarter-datev: `./out/.../<YYYY-MM>/datev/` (month-level datev folder)

Example (June 2024): `./out/2024/Q2/2024-06/...`

### Bulk Export (Whole Quarter / Year)

To produce the full quarterly folder structure (`./out/<YYYY>/Q1..Q4/<YYYY-MM>/...` with one shared `datev/` per quarter), loop monthly runs. The single-month run auto-groups into the right quarter folder — no year-mode switch needed.

PowerShell (Windows):

```powershell
# Full year (12 monthly runs → Q1..Q4 folders)
1..12 | ForEach-Object { uv run stripe-datev-cli.py download 2024 $_ }

# Single quarter (Q2 = months 4..6)
4..6  | ForEach-Object { uv run stripe-datev-cli.py download 2024 $_ }

# Validate every quarter of the year (checks each Q*/datev folder)
1,4,7,10 | ForEach-Object { uv run stripe-datev-cli.py validate_exports 2024 $_ }
```

Note: `download <year> 0` also exists but produces a flat `./out/<YYYY>/FULL_YEAR/` layout without quarter grouping. For the accountant-friendly quarterly structure use the monthly loop above.

Download options:

- `--pdf-workers`: parallel workers for PDF/receipt downloads (bounded to 1-24, default from `config.toml`)
- `--pdf-max-rps`: max PDF/receipt requests per second (default from `config.toml`, use `0` to disable throttling)
- `--pdf-timeout`: HTTP timeout in seconds for PDF/receipt downloads (default from `config.toml`)
- `--pdf-retries`: retries for transient PDF/receipt errors like 429/5xx (default from `config.toml`)
- `--skip-historical-warnings`: skip cross-month warning scan for earlier invoice status changes / credit notes
- `--include-historical-warnings`: force-enable historical warning scan
- `--skip-receipts`: skip Stripe payment receipt (HTML) downloads — only invoice PDFs (default from `config.toml:[download].skip_receipts`)
- `--include-receipts`: force-enable receipt downloads even if config defaults to skip

Command logs are written automatically to `out/<YYYY>/Q<1-4>/<YYYY-MM>/logs/download-<timestamp>.log` during each run (live, line-buffered). No manual redirect needed. If you still want to capture the raw terminal view (including progress counters with no ANSI re-writes), you can redirect on top:

```powershell
uv run stripe-datev-cli.py download 2024 6 *> out/2024/Q2/2024-06/logs/terminal.log
```

Default performance profile (in `config.toml` / `config.example.toml`):

- `download.pdf_workers = 23`
- `download.pdf_max_rps = 23`
- `download.pdf_timeout = 30`
- `download.pdf_retries = 4`
- `download.skip_historical_warnings = true`
- `download.skip_receipts = false` (set `true` to only download invoice PDFs, no HTML receipts)

Note on warning `unknown period for line item ... Payment for Invoice #...`:

- This warning comes from revenue-period detection when Stripe line items do not include a usable service period.
- Point-in-time periods (`period.start == period.end`) are treated as valid and do not raise this warning.
- In that case the exporter falls back to invoice creation/finalization timing for recognition.
- It is not evidence that invoices outside your selected month are being exported.

### Tax Classification Notes

- Reverse charge is only used for EU B2B cases with VAT-ID evidence (`eu_reverse_charge`).
- Non-EU invoices with zero tax are classified as outside-scope/export (`non_eu_outside_scope`) and are not labeled as reverse charge.
- EU invoices with zero tax and missing VAT ID are flagged with a warning and classified as `eu_b2c_missing_vat_id`.
- Missing country data is flagged with a warning and classified as `unknown_location`.

Optional `config.toml` settings:

- `company.country` (default: `DE`)
- `company.eu_country_codes` (optional override of EU country list for classifier)
- `accounts.revenue_non_eu_outside_scope` (default fallback: `accounts.account_reverse_charge_world`)
- `accounts.revenue_eu_b2c_missing_vat_id` (default fallback: `accounts.revenue_german_vat`)

### Where To Find Config Values (DATEV)

- `datev.berater_nr`:
  Use your DATEV *Beraternummer* from DATEV client/master data (Stammdaten) or your tax advisor.
- `datev.mandenten_nr`:
  Use the DATEV *Mandantennummer* of the target client in DATEV (Stammdaten).
- `accounts.*`:
  Use account numbers from your chart of accounts (e.g. SKR03/SKR04) that your bookkeeping setup already uses.
  Map each key to the account purpose named by the key, for example:
  `bank` = Stripe bank/clearing account, `stripe_fees` = Stripe fee expense account, `prap` = deferred revenue account.
- `datev_tax_key_*`:
  Use BU keys from your DATEV posting logic/tax setup.
  If you do not use an extra BU key for a case, keep it empty (`""`).

If you are unsure about any account/BU key, confirm the mapping with your accountant/tax advisor before importing.

### Only One Real Bank Account?

Even with one physical bank account, DATEV mapping typically uses at least one Stripe clearing flow:

- `accounts.bank` is the Stripe clearing account in exporter logic.
- `accounts.transit` is the payout-clearing bridge for reconciliation with your real bank statement.

Recommended with bank statement import:

1. `accounts.bank` = Stripe clearing account
2. `accounts.transit` = payout clearing account
3. Book imported Hausbank payout receipt against `accounts.transit`

Alternative without bank statement import for these payouts:

1. `accounts.bank` = Stripe clearing account
2. `accounts.transit` can be the Hausbank account
3. Do not additionally import/book the same payout from bank statement (avoid duplicates)

### Validate DATEV Files

```bash
python stripe-datev-cli.py validate_exports 2024 6
python stripe-datev-cli.py validate_exports --path out/2024/Q2/2024-06/datev
```

Validation checks:

- EXTF header signature/version/category
- Required DATEV columns present
- Data row column count consistency
- Amount format (German decimal comma), Soll/Haben flag, account numeric checks
- Belegdatum format (`DDMM`)

### Local Extension Layer

Local custom behavior can live in `stripe_datev_local/` so upstream merges stay low-conflict:

- `stripe_datev_local/tax_policy.py` for tax classification/country logic
- `stripe_datev_local/output_layout.py` for output folder/layout policy

```
python stripe-datev-cli.py fees <year> <month>
```

Shows a summary of all Stripe fees and contributions accrued in the given month (uses UTC, as Stripe does in their invoices, instead of the local timezone)

```
python stripe-datev-cli.py opos
python stripe-datev-cli.py opos <year> <month> <date>
```

Shows all unpaid invoices as of now, or as of the end of the given date. Useful to verify the balance of pRAP accounts at the end of a year.

```
python stripe-datev-cli.py preview <in_123...>
python stripe-datev-cli.py preview <ch_123...>
python stripe-datev-cli.py preview <txn_123...>
```

Shows a preview of all accounting records stemming from one invoice/charge/transaction. Useful to diff output when making changes to the accounting record generation logic.
