from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
import random
import time
import threading
import requests

RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
MAX_WORKERS_CAP = 24


class RequestRateLimiter:
  def __init__(self, max_requests_per_second):
    try:
      max_rps = int(max_requests_per_second)
    except Exception:
      max_rps = 0
    self.max_rps = max(0, max_rps)
    self._lock = threading.Lock()
    self._timestamps = deque()

  def wait_for_slot(self):
    if self.max_rps <= 0:
      return

    while True:
      sleep_for = 0.0
      with self._lock:
        now = time.monotonic()
        while self._timestamps and (now - self._timestamps[0]) >= 1.0:
          self._timestamps.popleft()
        if len(self._timestamps) < self.max_rps:
          self._timestamps.append(now)
          return
        sleep_for = 1.0 - (now - self._timestamps[0])
      if sleep_for > 0:
        time.sleep(min(sleep_for, 0.05))


def bounded_workers(requested_workers, default_workers=3):
  if requested_workers is None:
    requested_workers = default_workers
  try:
    workers = int(requested_workers)
  except Exception:
    workers = default_workers
  return max(1, min(workers, MAX_WORKERS_CAP))


def _retry_delay_seconds(attempt_idx, retry_after_header=None):
  backoff = min(10.0, 0.5 * (2 ** attempt_idx))
  if retry_after_header:
    try:
      retry_after = float(retry_after_header)
      backoff = max(backoff, retry_after)
    except Exception:
      pass
  return backoff + random.uniform(0.0, 0.2)


def download_url_to_file(url, file_path, timeout_seconds=30, max_retries=3, rate_limiter=None):
  last_error = None

  for attempt_idx in range(max_retries + 1):
    try:
      if rate_limiter is not None:
        rate_limiter.wait_for_slot()
      response = requests.get(url, timeout=timeout_seconds)
    except requests.RequestException as ex:
      last_error = str(ex)
      if attempt_idx < max_retries:
        time.sleep(_retry_delay_seconds(attempt_idx))
        continue
      return False, last_error

    if response.status_code == 200:
      with open(file_path, "wb") as fp:
        fp.write(response.content)
      return True, None

    if response.status_code in RETRYABLE_STATUS_CODES and attempt_idx < max_retries:
      retry_after = response.headers.get("Retry-After")
      time.sleep(_retry_delay_seconds(attempt_idx, retry_after))
      continue

    return False, "HTTP status {}".format(response.status_code)

  return False, last_error or "download failed"


def download_many(jobs, workers=3, timeout_seconds=30, max_retries=3, progress_every=100, max_requests_per_second=0):
  total = len(jobs)
  if total == 0:
    return {"total": 0, "downloaded": 0, "failed": 0}

  workers = bounded_workers(workers, default_workers=3)
  rate_limiter = RequestRateLimiter(max_requests_per_second)
  completed = 0
  failed = 0
  failures = []

  with ThreadPoolExecutor(max_workers=workers) as executor:
    futures = {}
    for job in jobs:
      futures[executor.submit(
        download_url_to_file,
        job["url"],
        job["file_path"],
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        rate_limiter=rate_limiter,
      )] = job

    for future in as_completed(futures):
      job = futures[future]
      try:
        ok, error = future.result()
      except Exception as ex:
        ok = False
        error = str(ex)

      completed += 1
      if not ok:
        failed += 1
        failures.append((job, error))

      if completed == total or completed % max(1, progress_every) == 0:
        print("Downloaded {}/{} file(s)".format(completed, total))

  for job, error in failures[:50]:
    print("Warning: failed to download {} -> {} ({})".format(
      job["url"], job["file_path"], error))
  if failed > 50:
    print("Warning: {} additional download failure(s) suppressed".format(
      failed - 50))

  return {
    "total": total,
    "downloaded": total - failed,
    "failed": failed,
  }
