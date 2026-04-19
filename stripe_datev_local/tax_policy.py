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

TAXABILITY_REASON_EXCLUDED_TERRITORY = "excluded_territory"

# Stripe Tax signals that the location is outside its tax-collection scope.
# For an EU merchant with Stripe Tax enabled, any of these on an EU-country
# customer effectively means an EU-excluded VAT zone (Azores, Madeira, Canary
# Islands, Ceuta, Melilla, Åland, Helgoland, Büsingen, French overseas, etc.),
# which is Drittland for German VAT purposes (§1 Abs. 2a UStG).
TAXABILITY_REASONS_OUTSIDE_SCOPE = (
  "excluded_territory",
  "not_supported",
  "jurisdiction_unsupported",
)


def _digits(s):
  return "".join(ch for ch in (s or "") if ch.isdigit())


def _es_postal_excluded(postal):
  # ES 35xxx = Las Palmas (Canary Islands), 38xxx = S.C. Tenerife (Canary Islands)
  # ES 51xxx = Ceuta, 52xxx = Melilla
  return postal.startswith(("35", "38", "51", "52"))


def _pt_postal_excluded(postal):
  # PT 9000-9499 = Madeira, 9500-9999 = Azores (all outside EU VAT area)
  digits = _digits(postal)
  if len(digits) < 4:
    return False
  try:
    code = int(digits[:4])
  except ValueError:
    return False
  return 9000 <= code <= 9999


def _fi_postal_excluded(postal):
  # FI 22xxx = Åland Islands
  return postal.startswith("22")


EU_EXCLUDED_POSTAL_PREDICATES = {
  "ES": _es_postal_excluded,
  "PT": _pt_postal_excluded,
  "FI": _fi_postal_excluded,
}


def postal_excluded_territory_name(country, postal_code):
  country = normalize_country_code(country)
  if country is None:
    return None
  predicate = EU_EXCLUDED_POSTAL_PREDICATES.get(country)
  if predicate is None:
    return None
  postal = (postal_code or "").strip()
  if not postal:
    return None
  if not predicate(postal):
    return None
  if country == "ES":
    if postal.startswith(("35", "38")):
      return "Canary Islands"
    if postal.startswith("51"):
      return "Ceuta"
    if postal.startswith("52"):
      return "Melilla"
  if country == "PT":
    digits = _digits(postal)
    try:
      code = int(digits[:4]) if len(digits) >= 4 else 0
    except ValueError:
      code = 0
    return "Azores" if code >= 9500 else "Madeira"
  if country == "FI":
    return "Åland"
  return "EU-excluded territory"


def get_invoice_postal_code(invoice):
  for path in [
      ["customer_shipping", "address", "postal_code"],
      ["customer_address", "postal_code"],
      ["customer_details", "address", "postal_code"],
  ]:
    value = nested_get(invoice, path)
    if value:
      return str(value)
  return None


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


def get_invoice_taxability_reasons(invoice):
  if invoice is None:
    return []

  reasons = []

  def collect(items):
    if not isinstance(items, (list, tuple)):
      return
    for item in items:
      reason = obj_get(item, "taxability_reason")
      if reason:
        reasons.append(str(reason))

  for path in [["total_taxes"], ["total_tax_amounts"]]:
    collect(nested_get(invoice, path))

  lines = nested_get(invoice, ["lines", "data"]) or []
  for line in lines:
    collect(obj_get(line, "taxes"))
    collect(obj_get(line, "tax_amounts"))

  return reasons


def get_outside_scope_taxability_reason(invoice):
  for reason in get_invoice_taxability_reasons(invoice):
    if reason in TAXABILITY_REASONS_OUTSIDE_SCOPE:
      return reason
  return None


def is_excluded_territory_invoice(invoice):
  return get_outside_scope_taxability_reason(invoice) is not None


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


def classify_tax_treatment(country, invoice_tax, merchant_country, has_eu_vat_id, eu_country_codes=None, is_excluded_territory=False):
  country = normalize_country_code(country)
  merchant_country = normalize_country_code(merchant_country) or "DE"
  tax_amount = _to_minor_amount(invoice_tax)
  tax_is_zero = tax_amount is None or tax_amount == 0

  if country is None or country == "UNKNOWN":
    return TAX_CLASS_UNKNOWN_LOCATION

  if is_excluded_territory and tax_is_zero and not has_eu_vat_id:
    return TAX_CLASS_NON_EU_OUTSIDE_SCOPE

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
  outside_scope_reason = get_outside_scope_taxability_reason(invoice)
  postal_code = get_invoice_postal_code(invoice)
  postal_territory = postal_excluded_territory_name(country, postal_code)
  excluded_territory = outside_scope_reason is not None or postal_territory is not None
  tax_classification = classify_tax_treatment(
    country=country,
    invoice_tax=invoice_tax,
    merchant_country=merchant_country,
    has_eu_vat_id=vat_id is not None,
    eu_country_codes=eu_country_codes,
    is_excluded_territory=excluded_territory,
  )

  info = None
  customer_is_eu = is_eu_country(country, eu_country_codes=eu_country_codes)
  if excluded_territory and tax_classification == TAX_CLASS_NON_EU_OUTSIDE_SCOPE and customer_is_eu:
    if postal_territory is not None:
      info = (
        "Classified as non-EU outside-scope (Drittland) — customer postal code {} in {} "
        "({}) is an EU-excluded VAT zone. Treated as §1 Abs. 2a UStG third territory for "
        "German VAT."
      ).format(postal_code, postal_territory, country)
    else:
      info = (
        "Classified as non-EU outside-scope (Drittland) — Stripe Tax reason '{}' on an EU "
        "country ({}). Customer is in an EU-excluded VAT zone (e.g. Azores, Madeira, Canary "
        "Islands, Ceuta, Melilla, Åland, Helgoland, Büsingen, French overseas territories). "
        "Treated as §1 Abs. 2a UStG third territory for German VAT."
      ).format(outside_scope_reason, country)

  return {
    "classification": tax_classification,
    "country": country,
    "vat_id": vat_id,
    "invoice_tax": invoice_tax,
    "invoice_total": invoice_total,
    "warning": get_tax_classification_warning(tax_classification),
    "info": info,
    "excluded_territory": excluded_territory,
    "eu_country_codes": eu_country_codes,
  }
