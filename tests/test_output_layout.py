import os
import tempfile
import unittest
from datetime import datetime

from stripe_datev_local import output_layout


class OutputLayoutTest(unittest.TestCase):

  def test_resolve_pdf_paths_creates_year_month_folder(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      file_path, legacy_path = output_layout.resolve_pdf_paths(
        tmpdir, "test.pdf", datetime(2024, 5, 15))

      self.assertTrue(file_path.endswith(os.path.join("2024", "05", "test.pdf")))
      self.assertEqual(legacy_path, os.path.join(tmpdir, "test.pdf"))
      self.assertTrue(os.path.isdir(os.path.join(tmpdir, "2024", "05")))

  def test_file_exists_checks_new_and_legacy_path(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      file_path, legacy_path = output_layout.resolve_pdf_paths(
        tmpdir, "test.pdf", datetime(2024, 5, 15))
      self.assertFalse(output_layout.file_exists(file_path, legacy_path))

      with open(legacy_path, "w") as fp:
        fp.write("ok")
      self.assertTrue(output_layout.file_exists(file_path, legacy_path))


if __name__ == "__main__":
  unittest.main()
