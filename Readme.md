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

- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/overview/`
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/monthly_recognition/`
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/datev/`
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/pdf/`
- `./out/<YYYY>/Q<1-4>/<YYYY-MM>/logs/` (for your run logs)

Example (June 2024): `./out/2024/Q2/2024-06/...`

Download options:

- `--pdf-workers`: parallel workers for PDF/receipt downloads (bounded to 1-24, default from `config.toml`)
- `--pdf-max-rps`: max PDF/receipt requests per second (default from `config.toml`, use `0` to disable throttling)
- `--pdf-timeout`: HTTP timeout in seconds for PDF/receipt downloads (default from `config.toml`)
- `--pdf-retries`: retries for transient PDF/receipt errors like 429/5xx (default from `config.toml`)
- `--skip-historical-warnings`: skip cross-month warning scan for earlier invoice status changes / credit notes
- `--include-historical-warnings`: force-enable historical warning scan

Store command logs in the month folder (PowerShell example):

```powershell
uv run stripe-datev-cli.py download 2024 6 --pdf-workers 23 --pdf-max-rps 23 --skip-historical-warnings *> out/2024/Q2/2024-06/logs/download.log
```

Default performance profile (in `config.toml` / `config.example.toml`):

- `download.pdf_workers = 23`
- `download.pdf_max_rps = 23`
- `download.pdf_timeout = 30`
- `download.pdf_retries = 4`
- `download.skip_historical_warnings = true`

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
