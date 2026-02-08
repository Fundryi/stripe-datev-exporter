import os


def quarter_for_month(month):
  month = int(month)
  if month < 1 or month > 12:
    raise ValueError("month must be in 1..12")
  return "Q{}".format(((month - 1) // 3) + 1)


def period_label(year, month):
  year = int(year)
  month = int(month)
  if month > 0:
    return "{:04d}-{:02d}".format(year, month)
  return "{:04d}-full".format(year)


def resolve_download_root(out_dir, year, month):
  year = int(year)
  month = int(month)
  year_dir = os.path.join(out_dir, "{:04d}".format(year))
  if month > 0:
    return os.path.join(
      year_dir,
      quarter_for_month(month),
      period_label(year, month),
    )
  return os.path.join(year_dir, "FULL_YEAR")


def ensure_download_dirs(out_dir, year, month):
  root_dir = resolve_download_root(out_dir, year, month)
  folders = {
    "root": root_dir,
  }
  for name in ["pdf", "overview", "monthly_recognition", "datev", "logs"]:
    folders[name] = os.path.join(root_dir, name)
  for path in folders.values():
    os.makedirs(path, exist_ok=True)
  return folders


def resolve_pdf_paths(pdf_dir, file_name, file_date):
  os.makedirs(pdf_dir, exist_ok=True)
  # New canonical layout keeps files directly in the run's pdf folder.
  # Legacy fallback supports older runs that used nested year/month folders.
  return (
    os.path.join(pdf_dir, file_name),
    os.path.join(pdf_dir, file_date.strftime("%Y"), file_date.strftime("%m"), file_name),
  )


def file_exists(new_file_path, legacy_file_path):
  return os.path.exists(new_file_path) or os.path.exists(legacy_file_path)
