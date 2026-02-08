import os


def resolve_pdf_paths(pdf_dir, file_name, file_date):
  monthly_dir = os.path.join(pdf_dir, file_date.strftime("%Y"), file_date.strftime("%m"))
  if not os.path.exists(monthly_dir):
    os.makedirs(monthly_dir, exist_ok=True)
  return os.path.join(monthly_dir, file_name), os.path.join(pdf_dir, file_name)


def file_exists(new_file_path, legacy_file_path):
  return os.path.exists(new_file_path) or os.path.exists(legacy_file_path)
