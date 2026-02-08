import os
import tempfile
import unittest

from stripe_datev_local import downloads


class _FakeResponse:
  def __init__(self, status_code, content=b"", headers=None):
    self.status_code = status_code
    self.content = content
    self.headers = headers or {}


class DownloadsTest(unittest.TestCase):

  def test_bounded_workers(self):
    self.assertEqual(downloads.bounded_workers(None), 3)
    self.assertEqual(downloads.bounded_workers(0), 1)
    self.assertEqual(downloads.bounded_workers(99), 24)
    self.assertEqual(downloads.bounded_workers(4), 4)

  def test_download_url_to_file_success(self):
    original_get = downloads.requests.get
    try:
      downloads.requests.get = lambda url, timeout=30: _FakeResponse(200, content=b"abc")
      with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "file.bin")
        ok, err = downloads.download_url_to_file("https://example.com", out, timeout_seconds=1, max_retries=0)
        self.assertTrue(ok)
        self.assertIsNone(err)
        with open(out, "rb") as fp:
          self.assertEqual(fp.read(), b"abc")
    finally:
      downloads.requests.get = original_get

  def test_download_url_to_file_retries_429_then_success(self):
    original_get = downloads.requests.get
    original_sleep = downloads.time.sleep
    calls = {"count": 0}
    try:
      def fake_get(url, timeout=30):
        calls["count"] += 1
        if calls["count"] == 1:
          return _FakeResponse(429, headers={"Retry-After": "0"})
        return _FakeResponse(200, content=b"ok")

      downloads.requests.get = fake_get
      downloads.time.sleep = lambda secs: None

      with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "file.bin")
        ok, err = downloads.download_url_to_file("https://example.com", out, timeout_seconds=1, max_retries=2)
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(calls["count"], 2)
    finally:
      downloads.requests.get = original_get
      downloads.time.sleep = original_sleep


if __name__ == "__main__":
  unittest.main()
