import pytz
import tomli

with open('config.toml', 'rb') as f:
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
}
download.update(config.get("download", {}))
