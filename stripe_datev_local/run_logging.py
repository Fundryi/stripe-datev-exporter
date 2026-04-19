import os
import sys
from contextlib import contextmanager
from datetime import datetime


class _Tee:
  def __init__(self, *streams):
    self.streams = streams

  def write(self, data):
    for stream in self.streams:
      try:
        stream.write(data)
      except Exception:
        pass
      try:
        stream.flush()
      except Exception:
        pass

  def flush(self):
    for stream in self.streams:
      try:
        stream.flush()
      except Exception:
        pass

  def isatty(self):
    return False


@contextmanager
def tee_run_log(logs_dir, prefix="download"):
  os.makedirs(logs_dir, exist_ok=True)
  timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
  log_path = os.path.join(logs_dir, "{}-{}.log".format(prefix, timestamp))
  log_file = open(log_path, "w", encoding="utf-8", buffering=1)

  orig_stdout = sys.stdout
  orig_stderr = sys.stderr
  sys.stdout = _Tee(orig_stdout, log_file)
  sys.stderr = _Tee(orig_stderr, log_file)
  try:
    yield log_path
  finally:
    sys.stdout = orig_stdout
    sys.stderr = orig_stderr
    log_file.close()
