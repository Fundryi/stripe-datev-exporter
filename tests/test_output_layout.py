import os
import tempfile
import unittest
from datetime import datetime

from stripe_datev_local import output_layout


class OutputLayoutTest(unittest.TestCase):

  def test_resolve_pdf_paths_uses_run_pdf_folder_and_legacy_fallback(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      file_path, legacy_path = output_layout.resolve_pdf_paths(
        tmpdir, "test.pdf", datetime(2024, 5, 15))

      self.assertEqual(file_path, os.path.join(tmpdir, "test.pdf"))
      self.assertEqual(
        legacy_path, os.path.join(tmpdir, "2024", "05", "test.pdf"))
      self.assertTrue(os.path.isdir(tmpdir))

  def test_file_exists_checks_new_and_legacy_path(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      file_path, legacy_path = output_layout.resolve_pdf_paths(
        tmpdir, "test.pdf", datetime(2024, 5, 15))
      self.assertFalse(output_layout.file_exists(file_path, legacy_path))

      os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
      with open(legacy_path, "w") as fp:
        fp.write("ok")
      self.assertTrue(output_layout.file_exists(file_path, legacy_path))

  def test_resolve_download_root_monthly(self):
    root = output_layout.resolve_download_root("out", 2024, 6)
    self.assertTrue(root.endswith(os.path.join("2024", "Q2", "2024-06")))

  def test_ensure_download_dirs_creates_expected_subfolders(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      paths = output_layout.ensure_download_dirs(tmpdir, 2024, 5)
      self.assertTrue(paths["root"].endswith(os.path.join("2024", "Q2", "2024-05")))
      for key in ["pdf", "overview", "monthly_recognition", "datev", "logs"]:
        self.assertTrue(os.path.isdir(paths[key]))


if __name__ == "__main__":
  unittest.main()
