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


def resolve_datev_dir(out_dir, year, month):
  root_dir = resolve_download_root(out_dir, year, month)
  if int(month) > 0:
    return os.path.join(os.path.dirname(root_dir), "datev")
  return os.path.join(root_dir, "datev")


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
  files_dir = os.path.join(root_dir, "files")
  # DATEV CSVs live one level up (at quarter level) for monthly runs,
  # so an accountant can import a whole quarter from a single folder.
  # Full-year runs (month=0) have no quarter grouping → datev stays at root.
  if int(month) > 0:
    datev_dir = os.path.join(os.path.dirname(root_dir), "datev")
  else:
    datev_dir = os.path.join(root_dir, "datev")

  folders = {
    "root": root_dir,
    "files": files_dir,
    "invoices": os.path.join(files_dir, "invoices"),
    "receipts": os.path.join(files_dir, "receipts"),
    "datev": datev_dir,
  }
  for name in ["overview", "monthly_recognition", "logs"]:
    folders[name] = os.path.join(root_dir, name)

  # Legacy lookup paths (not created) for backward-compatible existence checks
  folders["invoices_legacy_flat"] = os.path.join(root_dir, "invoices")
  folders["receipts_legacy_flat"] = os.path.join(root_dir, "receipts")
  folders["pdf_legacy"] = os.path.join(root_dir, "pdf")
  folders["datev_legacy_month"] = os.path.join(root_dir, "datev")

  os.makedirs(folders["root"], exist_ok=True)
  for name in ["files", "invoices", "receipts", "datev", "overview", "monthly_recognition", "logs"]:
    os.makedirs(folders[name], exist_ok=True)
  return folders


def resolve_pdf_paths(pdf_dir, file_name, file_date):
  os.makedirs(pdf_dir, exist_ok=True)
  return (
    os.path.join(pdf_dir, file_name),
    os.path.join(pdf_dir, file_date.strftime("%Y"), file_date.strftime("%m"), file_name),
  )


def resolve_document_paths(target_dir, legacy_dirs, file_name, file_date):
  os.makedirs(target_dir, exist_ok=True)
  new_path = os.path.join(target_dir, file_name)
  legacy_paths = []
  for legacy in legacy_dirs or []:
    if not legacy:
      continue
    legacy_paths.append(os.path.join(legacy, file_name))
    legacy_paths.append(os.path.join(
      legacy, file_date.strftime("%Y"), file_date.strftime("%m"), file_name))
  return new_path, legacy_paths


def file_exists(new_file_path, legacy_file_path):
  if isinstance(legacy_file_path, (list, tuple)):
    return os.path.exists(new_file_path) or any(
      os.path.exists(p) for p in legacy_file_path)
  return os.path.exists(new_file_path) or os.path.exists(legacy_file_path)
