import os
from pathlib import Path

import pytz
import tomli


def _resolve_config_path():
  env_config_path = os.environ.get("STRIPE_DATEV_CONFIG")
  candidates = []

  if env_config_path:
    candidates.append(Path(env_config_path).expanduser())

  # Keep historical behavior first: prefer config.toml in the current folder.
  candidates.append(Path.cwd() / "config.toml")

  # Fallback: config.toml next to the repository root (parent of package dir).
  repo_root = Path(__file__).resolve().parent.parent
  candidates.append(repo_root / "config.toml")

  for path in candidates:
    if path.is_file():
      return path

  raise FileNotFoundError(
    "config.toml not found. Checked: {}".format(", ".join(str(p) for p in candidates))
  )


with _resolve_config_path().open('rb') as f:
  config = tomli.load(f)

company = config["company"]
accounting_tz = pytz.timezone(company["timezone"])

datev = config["datev"]
accounts = config["accounts"]

download = {
  "pdf_workers": 23,
  "pdf_max_rps": 23,
  "pdf_timeout": 30,
  "pdf_retries": 4,
  "skip_historical_warnings": True,
  "skip_receipts": False,
  "auto_fill_account_numbers": True,
}
download.update(config.get("download", {}))
