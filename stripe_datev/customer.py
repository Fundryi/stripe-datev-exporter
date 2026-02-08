from datetime import datetime, timezone
import json
import os.path
import sys
import stripe

from stripe_datev import config, output

FILL_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(
  os.path.realpath(__file__))), '.fill_account_numbers_log.json')

customers_cached = {}


def retrieveCustomer(id):
  if isinstance(id, str):
    if id in customers_cached:
      return customers_cached[id]
    cus = stripe.Customer.retrieve(id, expand=["tax_ids"])
    customers_cached[cus.id] = cus
    return cus
  elif isinstance(id, stripe.Customer):
    customers_cached[id.id] = id
    return id
  else:
    raise Exception("Unexpected retrieveCustomer() argument: {}".format(id))


def getCustomerName(customer):
  if customer.get("deleted", False):
    return customer.id
  if customer.description is not None:
    return customer.description
  else:
    return customer.name


tax_ids_cached = {}


def getCustomerTaxId(customer):
  tax_ids = _obj_get(customer, "tax_ids")
  if tax_ids is not None:
    return _find_eu_vat_id(tax_ids)

  customer_id = _obj_get(customer, "id")
  if customer_id in tax_ids_cached:
    return tax_ids_cached[customer_id]
  if customer_id is None:
    return None

  ids = stripe.Customer.list_tax_ids(customer_id, limit=10).data
  tax_id = _find_eu_vat_id(ids)
  tax_ids_cached[customer_id] = tax_id
  return tax_id


EU_COUNTRY_CODES = [
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
]

EU_VAT_PREFIXES = set(EU_COUNTRY_CODES + ["EL"])

TAX_CLASS_EU_VAT_CHARGED = "eu_vat_charged"
TAX_CLASS_EU_REVERSE_CHARGE = "eu_reverse_charge"
TAX_CLASS_EU_B2C_MISSING_VAT_ID = "eu_b2c_missing_vat_id"
TAX_CLASS_NON_EU_OUTSIDE_SCOPE = "non_eu_outside_scope"
TAX_CLASS_UNKNOWN_LOCATION = "unknown_location"
TAX_CLASS_TAX_CHARGED_OTHER = "tax_charged_other"

WARNING_EU_MISSING_VAT_ID = "EU customer without VAT ID and no VAT charged — should be B2C VAT, check setup"
WARNING_UNKNOWN_LOCATION = "Cannot determine customer country — cannot safely classify tax treatment"


def normalizeCountryCode(code):
  if code is None:
    return None
  code = str(code).strip().upper()
  if code == "":
    return None
  return code


def isEUCountry(code):
  code = normalizeCountryCode(code)
  return code in EU_COUNTRY_CODES if code is not None else False


def _obj_get(value, key, default=None):
  if value is None:
    return default
  if isinstance(value, dict):
    return value.get(key, default)
  try:
    return value.get(key, default)
  except Exception:
    return getattr(value, key, default)


def _nested_get(value, path, default=None):
  cursor = value
  for key in path:
    cursor = _obj_get(cursor, key)
    if cursor is None:
      return default
  return cursor


def _iter_tax_ids(tax_ids):
  if tax_ids is None:
    return []

  if isinstance(tax_ids, list):
    return tax_ids

  data = _obj_get(tax_ids, "data")
  if isinstance(data, list):
    return data

  try:
    return list(tax_ids)
  except Exception:
    return []


def _tax_id_value(tax_id):
  value = _obj_get(tax_id, "value")
  if value is None:
    return None
  value = str(value).strip().upper()
  return value or None


def _tax_id_is_eu_vat(tax_id):
  tax_type = _obj_get(tax_id, "type")
  tax_type = str(tax_type).strip().lower() if tax_type is not None else ""
  value = _tax_id_value(tax_id)
  if value is None:
    return False
  if tax_type == "eu_vat":
    return True
  return value[:2] in EU_VAT_PREFIXES


def _find_eu_vat_id(tax_ids):
  for tax_id in _iter_tax_ids(tax_ids):
    if _tax_id_is_eu_vat(tax_id):
      return _tax_id_value(tax_id)
  return None


def getInvoiceTaxId(invoice):
  if invoice is None:
    return None

  for tax_ids in [
      _obj_get(invoice, "customer_tax_ids"),
      _nested_get(invoice, ["customer_details", "tax_ids"]),
  ]:
    vat_id = _find_eu_vat_id(tax_ids)
    if vat_id is not None:
      return vat_id
  return None


def resolveCustomerCountry(customer, invoice=None):
  if invoice is not None:
    for path in [
        ["customer_shipping", "address", "country"],
        ["customer_address", "country"],
        ["customer_details", "address", "country"],
    ]:
      country = normalizeCountryCode(_nested_get(invoice, path))
      if country is not None:
        return country

  country = normalizeCountryCode(_nested_get(customer, ["address", "country"]))
  if country is not None:
    return country

  customer_id = _obj_get(customer, "id")
  if customer_id is not None:
    try:
      refreshed = retrieveCustomer(customer_id)
      country = normalizeCountryCode(_nested_get(refreshed, ["address", "country"]))
      if country is not None:
        return country
    except Exception:
      pass

  return "unknown"


def getTaxClassificationWarning(tax_classification):
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


def classifyTaxTreatment(country, invoice_tax, merchant_country, has_eu_vat_id):
  country = normalizeCountryCode(country)
  merchant_country = normalizeCountryCode(merchant_country) or "DE"
  tax_amount = _to_minor_amount(invoice_tax)
  tax_is_zero = tax_amount is None or tax_amount == 0

  if country is None or country == "UNKNOWN":
    return TAX_CLASS_UNKNOWN_LOCATION

  if isEUCountry(country):
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


def classifyInvoiceTaxTreatment(customer, invoice=None, checkout_session=None, merchant_country=None):
  merchant_country = normalizeCountryCode(merchant_country)
  if merchant_country is None:
    merchant_country = normalizeCountryCode(config.company.get("country", "DE")) or "DE"

  invoice_tax = None
  invoice_total = None
  if invoice is not None:
    invoice_tax = _obj_get(invoice, "tax")
    invoice_total = _obj_get(invoice, "total")
  elif checkout_session is not None:
    invoice_tax = _nested_get(checkout_session, ["total_details", "amount_tax"])
    invoice_total = _obj_get(checkout_session, "amount_total")

  country = resolveCustomerCountry(customer, invoice=invoice)
  vat_id = getInvoiceTaxId(invoice) or getCustomerTaxId(customer)
  tax_classification = classifyTaxTreatment(
    country=country,
    invoice_tax=invoice_tax,
    merchant_country=merchant_country,
    has_eu_vat_id=vat_id is not None,
  )

  return {
    "classification": tax_classification,
    "country": country,
    "vat_id": vat_id,
    "invoice_tax": invoice_tax,
    "invoice_total": invoice_total,
    "warning": getTaxClassificationWarning(tax_classification),
  }


def _account_value(key, fallback_key=None, default=""):
  if key in config.accounts:
    return str(config.accounts[key])
  if fallback_key and fallback_key in config.accounts:
    return str(config.accounts[fallback_key])
  return str(default)


def getAccountingProps(customer, invoice=None, checkout_session=None):
  merchant_country = normalizeCountryCode(config.company.get("country", "DE")) or "DE"

  props = {
    "vat_region": "World",
  }

  finalized_at = _nested_get(invoice, ["status_transitions", "finalized_at"])
  customer_metadata = _obj_get(customer, "metadata") or {}
  if (invoice is None or finalized_at is None or datetime.fromtimestamp(finalized_at, timezone.utc) >= datetime(2022, 1, 1, 0, 0).astimezone(config.accounting_tz)):
    if not customer_metadata.get("accountNumber", None):
      raise Exception("Expected 'accountNumber' in metadata")
    props["customer_account"] = customer_metadata["accountNumber"]
  else:
    props["customer_account"] = str(config.accounts["sammel_debitor"])

  tax_context = classifyInvoiceTaxTreatment(
    customer,
    invoice=invoice,
    checkout_session=checkout_session,
    merchant_country=merchant_country,
  )
  country = tax_context["country"]
  invoice_tax = tax_context["invoice_tax"]
  invoice_total = tax_context["invoice_total"]
  vat_id = tax_context["vat_id"]
  tax_classification = tax_context["classification"]

  # use tax status at time of invoice creation
  automatic_tax_enabled = bool(_nested_get(invoice, ["automatic_tax", "enabled"]))
  customer_tax_exempt = _obj_get(invoice, "customer_tax_exempt")
  if invoice is not None and customer_tax_exempt is not None and not automatic_tax_enabled:
    tax_exempt = customer_tax_exempt
  else:
    tax_exempt = _obj_get(customer, "tax_exempt")
  if tax_exempt is None:
    tax_exempt = "none"

  props = dict(props, **{
    "country": country,
    "vat_id": vat_id,
    "tax_exempt": tax_exempt,
    "invoice_tax": invoice_tax,
    "invoice_total": invoice_total,
    "tax_classification": tax_classification,
    "datev_tax_key_invoice": "",
    "datev_tax_key_payment": "",
  })

  if country == merchant_country:
    if invoice is not None and invoice_tax is None:
      print("Warning: no tax in {} invoice".format(merchant_country),
            _obj_get(invoice, "id", "n/a"))
    if tax_exempt != "none":
      print("Warning: {} customer tax status is".format(
        merchant_country), tax_exempt, _obj_get(customer, "id", "n/a"))
    props["revenue_account"] = _account_value("revenue_german_vat")
    props["datev_tax_key_invoice"] = _account_value("datev_tax_key_germany_invoice")
    props["datev_tax_key_payment"] = _account_value("datev_tax_key_germany_payment")
    props["vat_region"] = merchant_country
    return props

  if isEUCountry(country):
    props["vat_region"] = "EU"
  elif country == "unknown":
    props["vat_region"] = "Unknown"

  warning = tax_context["warning"]
  if warning:
    invoice_or_session_id = "n/a"
    if invoice is not None:
      invoice_or_session_id = _obj_get(invoice, "id", "n/a")
    elif checkout_session is not None:
      invoice_or_session_id = _obj_get(checkout_session, "id", "n/a")
    print("Warning: {} {} {}".format(
      warning, _obj_get(customer, "id", "n/a"), invoice_or_session_id))

  if tax_classification == TAX_CLASS_EU_REVERSE_CHARGE:
    props["revenue_account"] = _account_value("revenue_reverse_charge_eu")
    props["datev_tax_key_invoice"] = _account_value("datev_tax_key_reverse_invoice")
    props["datev_tax_key_payment"] = _account_value("datev_tax_key_reverse_payment")
    return props

  if tax_classification == TAX_CLASS_NON_EU_OUTSIDE_SCOPE:
    props["revenue_account"] = _account_value(
      "revenue_non_eu_outside_scope",
      fallback_key="account_reverse_charge_world",
    )
    return props

  if tax_classification == TAX_CLASS_EU_B2C_MISSING_VAT_ID:
    props["revenue_account"] = _account_value(
      "revenue_eu_b2c_missing_vat_id",
      fallback_key="revenue_german_vat",
    )
    props["datev_tax_key_invoice"] = _account_value("datev_tax_key_germany_invoice")
    props["datev_tax_key_payment"] = _account_value("datev_tax_key_germany_payment")
    return props

  if tax_classification == TAX_CLASS_UNKNOWN_LOCATION:
    props["revenue_account"] = _account_value(
      "revenue_unknown_location",
      fallback_key="revenue_non_eu_outside_scope",
      default=_account_value("account_reverse_charge_world"),
    )
    return props

  props["revenue_account"] = _account_value("revenue_german_vat")
  props["datev_tax_key_invoice"] = _account_value("datev_tax_key_germany_invoice")
  props["datev_tax_key_payment"] = _account_value("datev_tax_key_germany_payment")
  return props

def validate_customers():
  customer_count = 0
  for customer in stripe.Customer.list(expand=["data.tax_ids"]).auto_paging_iter():
    if not customer.address:
      print("Warning: customer without address", customer.id)

    if customer.tax_exempt == "exempt":
      print("Warning: exempt customer", customer.id)

    getAccountingProps(customer)

    customer_count += 1

  print("Validated {} customers".format(customer_count))


def fill_account_numbers():
  highest_account_number = None
  fill_customers = []
  for customer in stripe.Customer.list().auto_paging_iter():
    if "accountNumber" in customer.metadata:
      highest_account_number = int(customer.metadata["accountNumber"])
      break
    fill_customers.append(customer)

  if highest_account_number is None:
    highest_account_number = 10100 - 1

  print("{} customers without account number, highest number is {}".format(
    len(fill_customers), highest_account_number))

  modified = []
  for customer in reversed(fill_customers):
    # print(customer.id, customer.metadata)

    highest_account_number += 1
    metadata_new = {
      "accountNumber": str(highest_account_number)
    }

    for old_key in ["subscribedNetPrice", "subscribedProduct", "subscribedProductName", "subscribedTaxRate", "subscribedTotal"]:
      if old_key in customer.metadata:
        metadata_new[old_key] = ""

    # print("Update", metadata_new)
    stripe.Customer.modify(customer.id, metadata=metadata_new)
    modified.append(customer.id)

    print(customer.id, highest_account_number)

  with open(FILL_LOG_PATH, 'w') as f:
    json.dump(modified, f)
  print("Saved log of {} modified customer(s) to {}".format(
    len(modified), FILL_LOG_PATH))


def clear_account_numbers():
  if not os.path.exists(FILL_LOG_PATH):
    print("No fill log found at {}".format(FILL_LOG_PATH))
    print("Nothing to undo.")
    return

  with open(FILL_LOG_PATH, 'r') as f:
    customer_ids = json.load(f)

  print("Found {} customer(s) to undo".format(len(customer_ids)))
  count = 0
  for cid in customer_ids:
    stripe.Customer.modify(cid, metadata={"accountNumber": ""})
    print("Cleared", cid)
    count += 1

  os.remove(FILL_LOG_PATH)
  print("Cleared accountNumber from {} customer(s), log removed".format(count))


def list_account_numbers(file_path):
  customer_it = stripe.Customer.list(
    expand=["data.tax_ids"]).auto_paging_iter()
  if file_path is None:
    output.printAccounts(sys.stdout, customer_it)
  else:
    with open(file_path, "w", encoding="latin-1", errors="replace") as fp:
      output.printAccounts(fp, customer_it)
