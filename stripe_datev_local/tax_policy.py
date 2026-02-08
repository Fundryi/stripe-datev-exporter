DEFAULT_EU_COUNTRY_CODES = (
  "AT",
  "BE",
  "BG",
  "CY",
  "CZ",
  "DK",
  "EE",
  "FI",
  "FR",
  "DE",
  "GR",
  "HU",
  "IE",
  "IT",
  "LV",
  "LT",
  "LU",
  "MT",
  "NL",
  "PL",
  "PT",
  "RO",
  "SK",
  "SI",
  "ES",
  "SE",
)

TAX_CLASS_EU_VAT_CHARGED = "eu_vat_charged"
TAX_CLASS_EU_REVERSE_CHARGE = "eu_reverse_charge"
TAX_CLASS_EU_B2C_MISSING_VAT_ID = "eu_b2c_missing_vat_id"
TAX_CLASS_NON_EU_OUTSIDE_SCOPE = "non_eu_outside_scope"
TAX_CLASS_UNKNOWN_LOCATION = "unknown_location"
TAX_CLASS_TAX_CHARGED_OTHER = "tax_charged_other"

WARNING_EU_MISSING_VAT_ID = "EU customer without VAT ID and no VAT charged — should be B2C VAT, check setup"
WARNING_UNKNOWN_LOCATION = "Cannot determine customer country — cannot safely classify tax treatment"


def obj_get(value, key, default=None):
  if value is None:
    return default
  if isinstance(value, dict):
    return value.get(key, default)
  try:
    return value.get(key, default)
  except Exception:
    return getattr(value, key, default)


def nested_get(value, path, default=None):
  cursor = value
  for key in path:
    cursor = obj_get(cursor, key)
    if cursor is None:
      return default
  return cursor


def normalize_country_code(code):
  if code is None:
    return None
  code = str(code).strip().upper()
  if code == "":
    return None
  return code


def resolve_eu_country_codes(company_config=None, eu_country_codes=None):
  source = eu_country_codes
  if source is None and company_config is not None:
    source = obj_get(company_config, "eu_country_codes")

  if source is None:
    return DEFAULT_EU_COUNTRY_CODES

  if isinstance(source, str):
    source = source.split(",")

  if not isinstance(source, (list, tuple, set)):
    return DEFAULT_EU_COUNTRY_CODES

  normalized = []
  for code in source:
    code = normalize_country_code(code)
    if code is not None and code not in normalized:
      normalized.append(code)
  if len(normalized) == 0:
    return DEFAULT_EU_COUNTRY_CODES
  return tuple(normalized)


def is_eu_country(code, eu_country_codes=None):
  country = normalize_country_code(code)
  if country is None:
    return False
  return country in resolve_eu_country_codes(eu_country_codes=eu_country_codes)


def _eu_vat_prefixes(eu_country_codes=None):
  codes = list(resolve_eu_country_codes(eu_country_codes=eu_country_codes))
  return set(codes + ["EL"])


def iter_tax_ids(tax_ids):
  if tax_ids is None:
    return []

  if isinstance(tax_ids, list):
    return tax_ids

  data = obj_get(tax_ids, "data")
  if isinstance(data, list):
    return data

  try:
    return list(tax_ids)
  except Exception:
    return []


def tax_id_value(tax_id):
  value = obj_get(tax_id, "value")
  if value is None:
    return None
  value = str(value).strip().upper()
  return value or None


def tax_id_is_eu_vat(tax_id, eu_country_codes=None):
  tax_type = obj_get(tax_id, "type")
  tax_type = str(tax_type).strip().lower() if tax_type is not None else ""
  value = tax_id_value(tax_id)
  if value is None:
    return False
  if tax_type == "eu_vat":
    return True
  return value[:2] in _eu_vat_prefixes(eu_country_codes=eu_country_codes)


def find_eu_vat_id(tax_ids, eu_country_codes=None):
  for tax_id in iter_tax_ids(tax_ids):
    if tax_id_is_eu_vat(tax_id, eu_country_codes=eu_country_codes):
      return tax_id_value(tax_id)
  return None


def get_invoice_tax_id(invoice, eu_country_codes=None):
  if invoice is None:
    return None

  for tax_ids in [
      obj_get(invoice, "customer_tax_ids"),
      nested_get(invoice, ["customer_details", "tax_ids"]),
  ]:
    vat_id = find_eu_vat_id(tax_ids, eu_country_codes=eu_country_codes)
    if vat_id is not None:
      return vat_id
  return None


def resolve_customer_country(customer, invoice=None, retrieve_customer_by_id=None):
  if invoice is not None:
    for path in [
        ["customer_shipping", "address", "country"],
        ["customer_address", "country"],
        ["customer_details", "address", "country"],
    ]:
      country = normalize_country_code(nested_get(invoice, path))
      if country is not None:
        return country

  country = normalize_country_code(nested_get(customer, ["address", "country"]))
  if country is not None:
    return country

  customer_id = obj_get(customer, "id")
  if customer_id is not None and retrieve_customer_by_id is not None:
    try:
      refreshed = retrieve_customer_by_id(customer_id)
      country = normalize_country_code(nested_get(refreshed, ["address", "country"]))
      if country is not None:
        return country
    except Exception:
      pass

  return "unknown"


def get_tax_classification_warning(tax_classification):
  if tax_classification == TAX_CLASS_EU_B2C_MISSING_VAT_ID:
    return WARNING_EU_MISSING_VAT_ID
  if tax_classification == TAX_CLASS_UNKNOWN_LOCATION:
    return WARNING_UNKNOWN_LOCATION
  return None


def _to_minor_amount(value):
  if value is None:
    return None
  try:
    return int(value)
  except Exception:
    return None


def classify_tax_treatment(country, invoice_tax, merchant_country, has_eu_vat_id, eu_country_codes=None):
  country = normalize_country_code(country)
  merchant_country = normalize_country_code(merchant_country) or "DE"
  tax_amount = _to_minor_amount(invoice_tax)
  tax_is_zero = tax_amount is None or tax_amount == 0

  if country is None or country == "UNKNOWN":
    return TAX_CLASS_UNKNOWN_LOCATION

  if is_eu_country(country, eu_country_codes=eu_country_codes):
    if tax_amount is not None and tax_amount > 0:
      return TAX_CLASS_EU_VAT_CHARGED
    if tax_is_zero and country != merchant_country and has_eu_vat_id:
      return TAX_CLASS_EU_REVERSE_CHARGE
    if tax_is_zero:
      return TAX_CLASS_EU_B2C_MISSING_VAT_ID
    return TAX_CLASS_TAX_CHARGED_OTHER

  if tax_is_zero:
    return TAX_CLASS_NON_EU_OUTSIDE_SCOPE
  return TAX_CLASS_TAX_CHARGED_OTHER


def classify_invoice_tax_treatment(customer, get_customer_tax_id, invoice=None, checkout_session=None, merchant_country=None, eu_country_codes=None, retrieve_customer_by_id=None):
  merchant_country = normalize_country_code(merchant_country) or "DE"
  eu_country_codes = resolve_eu_country_codes(eu_country_codes=eu_country_codes)

  invoice_tax = None
  invoice_total = None
  if invoice is not None:
    invoice_tax = obj_get(invoice, "tax")
    invoice_total = obj_get(invoice, "total")
  elif checkout_session is not None:
    invoice_tax = nested_get(checkout_session, ["total_details", "amount_tax"])
    invoice_total = obj_get(checkout_session, "amount_total")

  country = resolve_customer_country(
    customer,
    invoice=invoice,
    retrieve_customer_by_id=retrieve_customer_by_id,
  )
  vat_id = get_invoice_tax_id(
    invoice, eu_country_codes=eu_country_codes) or get_customer_tax_id(customer)
  tax_classification = classify_tax_treatment(
    country=country,
    invoice_tax=invoice_tax,
    merchant_country=merchant_country,
    has_eu_vat_id=vat_id is not None,
    eu_country_codes=eu_country_codes,
  )

  return {
    "classification": tax_classification,
    "country": country,
    "vat_id": vat_id,
    "invoice_tax": invoice_tax,
    "invoice_total": invoice_total,
    "warning": get_tax_classification_warning(tax_classification),
    "eu_country_codes": eu_country_codes,
  }
