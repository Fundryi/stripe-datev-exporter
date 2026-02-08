import csv
from datetime import datetime
import os
import re


EXPECTED_HEADER_PREFIX = ["EXTF", "700", "21", "Buchungsstapel", "5"]
AMOUNT_RE = re.compile(r"^-?\d+,\d{2}$")
DATE_RE = re.compile(r"^\d{4}$")
DIGITS_RE = re.compile(r"^\d+$")


def _normalize_header_cell(value):
  if value is None:
    return ""
  return str(value).strip().strip('"')


def _find_index(fields, field_name):
  for idx, field in enumerate(fields):
    if field == field_name:
      return idx
  return None


def _safe_value(row, idx):
  if idx is None:
    return ""
  if idx >= len(row):
    return ""
  return row[idx].strip()


def _validate_belegdatum(belegdatum):
  if not DATE_RE.match(belegdatum):
    return False
  try:
    datetime.strptime(belegdatum + "2000", "%d%m%Y")
    return True
  except ValueError:
    return False


def validate_datev_file(path):
  errors = []
  rows_checked = 0

  with open(path, "r", encoding="latin1", errors="replace", newline="") as fp:
    rows = list(csv.reader(fp, delimiter=";", quotechar='"'))

  if len(rows) < 2:
    return {
      "path": path,
      "rows_checked": rows_checked,
      "errors": ["file has fewer than 2 header rows"],
    }

  header = [_normalize_header_cell(value) for value in rows[0]]
  fields = rows[1]

  for idx, expected in enumerate(EXPECTED_HEADER_PREFIX):
    if idx >= len(header) or header[idx] != expected:
      errors.append("header prefix mismatch at col {} (expected {!r}, got {!r})".format(
        idx, expected, header[idx] if idx < len(header) else None))

  required_fields = [
    "Umsatz (ohne Soll/Haben-Kz)",
    "Soll/Haben-Kennzeichen",
    "Konto",
    "Gegenkonto (ohne BU-Schlüssel)",
    "Belegdatum",
  ]
  missing_fields = [name for name in required_fields if _find_index(fields, name) is None]
  for name in missing_fields:
    errors.append("missing required field: {}".format(name))

  idx_amount = _find_index(fields, "Umsatz (ohne Soll/Haben-Kz)")
  idx_shkz = _find_index(fields, "Soll/Haben-Kennzeichen")
  idx_konto = _find_index(fields, "Konto")
  idx_gegenkonto = _find_index(fields, "Gegenkonto (ohne BU-Schlüssel)")
  idx_bu = _find_index(fields, "BU-Schlüssel")
  idx_belegdatum = _find_index(fields, "Belegdatum")

  expected_len = len(fields)
  for line_no, row in enumerate(rows[2:], start=3):
    rows_checked += 1
    if len(row) != expected_len:
      errors.append("line {} has {} columns, expected {}".format(
        line_no, len(row), expected_len))
      continue

    amount = _safe_value(row, idx_amount)
    if amount == "" or not AMOUNT_RE.match(amount):
      errors.append("line {} invalid amount format: {!r}".format(line_no, amount))

    shkz = _safe_value(row, idx_shkz)
    if shkz not in ("S", "H"):
      errors.append("line {} invalid Soll/Haben-Kennzeichen: {!r}".format(
        line_no, shkz))

    konto = _safe_value(row, idx_konto)
    if konto == "" or not DIGITS_RE.match(konto):
      errors.append("line {} invalid Konto: {!r}".format(line_no, konto))

    gegenkonto = _safe_value(row, idx_gegenkonto)
    if gegenkonto == "" or not DIGITS_RE.match(gegenkonto):
      errors.append("line {} invalid Gegenkonto: {!r}".format(line_no, gegenkonto))

    bu = _safe_value(row, idx_bu)
    if bu != "" and not DIGITS_RE.match(bu):
      errors.append("line {} invalid BU-Schluessel: {!r}".format(line_no, bu))

    belegdatum = _safe_value(row, idx_belegdatum)
    if not _validate_belegdatum(belegdatum):
      errors.append("line {} invalid Belegdatum: {!r}".format(line_no, belegdatum))

  return {
    "path": path,
    "rows_checked": rows_checked,
    "errors": errors,
  }


def validate_datev_folder(datev_dir):
  files = sorted(
    os.path.join(datev_dir, name)
    for name in os.listdir(datev_dir)
    if name.lower().endswith(".csv")
  )
  errors = []
  rows_checked = 0

  for path in files:
    result = validate_datev_file(path)
    rows_checked += result["rows_checked"]
    for err in result["errors"]:
      errors.append("{}: {}".format(os.path.basename(path), err))

  return {
    "files_checked": len(files),
    "rows_checked": rows_checked,
    "errors_count": len(errors),
    "errors": errors,
  }
