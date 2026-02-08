import csv
import os
import tempfile
import unittest

from stripe_datev import output as datev_output
from stripe_datev_local import datev_validation


class DatevValidationTest(unittest.TestCase):

  def _write_extf_file(self, path, amount="12,34"):
    header = [
      "EXTF", "700", "21", "Buchungsstapel", "5",
      "20260208120000", "", "BH", "", "",
      "1", "1", "20240101", "4", "20240401", "20240430",
      "Test", "", "1", "0", "0",
    ]
    fields = datev_output.fields
    row = [""] * len(fields)
    row[fields.index("Umsatz (ohne Soll/Haben-Kz)")] = amount
    row[fields.index("Soll/Haben-Kennzeichen")] = "S"
    row[fields.index("Konto")] = "8400"
    row[fields.index("Gegenkonto (ohne BU-Schlüssel)")] = "10001"
    row[fields.index("BU-Schlüssel")] = "40"
    row[fields.index("Belegdatum")] = "3004"

    with open(path, "w", encoding="latin1", newline="") as fp:
      writer = csv.writer(fp, delimiter=";", quotechar='"')
      writer.writerow(header)
      writer.writerow(fields)
      writer.writerow(row)

  def test_validate_datev_file_success(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      path = os.path.join(tmpdir, "EXTF_2024-04_Revenue.csv")
      self._write_extf_file(path, amount="12,34")

      result = datev_validation.validate_datev_file(path)
      self.assertEqual(result["rows_checked"], 1)
      self.assertEqual(result["errors"], [])

  def test_validate_datev_file_invalid_amount(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      path = os.path.join(tmpdir, "EXTF_2024-04_Revenue.csv")
      self._write_extf_file(path, amount="12.34")

      result = datev_validation.validate_datev_file(path)
      self.assertEqual(result["rows_checked"], 1)
      self.assertTrue(any("invalid amount format" in err for err in result["errors"]))

  def test_validate_datev_folder(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      self._write_extf_file(os.path.join(tmpdir, "EXTF_A.csv"), amount="12,34")
      self._write_extf_file(os.path.join(tmpdir, "EXTF_B.csv"), amount="56,78")

      result = datev_validation.validate_datev_folder(tmpdir)
      self.assertEqual(result["files_checked"], 2)
      self.assertEqual(result["rows_checked"], 2)
      self.assertEqual(result["errors_count"], 0)


if __name__ == "__main__":
  unittest.main()
