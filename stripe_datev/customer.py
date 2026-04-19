from datetime import datetime, timezone
import json
import os.path
import sys
import stripe

from stripe_datev import config, output
from stripe_datev_local import tax_policy

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


TAX_CLASS_EU_VAT_CHARGED = tax_policy.TAX_CLASS_EU_VAT_CHARGED
TAX_CLASS_EU_REVERSE_CHARGE = tax_policy.TAX_CLASS_EU_REVERSE_CHARGE
TAX_CLASS_EU_B2C_MISSING_VAT_ID = tax_policy.TAX_CLASS_EU_B2C_MISSING_VAT_ID
TAX_CLASS_NON_EU_OUTSIDE_SCOPE = tax_policy.TAX_CLASS_NON_EU_OUTSIDE_SCOPE
TAX_CLASS_UNKNOWN_LOCATION = tax_policy.TAX_CLASS_UNKNOWN_LOCATION
TAX_CLASS_TAX_CHARGED_OTHER = tax_policy.TAX_CLASS_TAX_CHARGED_OTHER

WARNING_EU_MISSING_VAT_ID = tax_policy.WARNING_EU_MISSING_VAT_ID
WARNING_UNKNOWN_LOCATION = tax_policy.WARNING_UNKNOWN_LOCATION


def _obj_get(value, key, default=None):
  return tax_policy.obj_get(value, key, default)


def _nested_get(value, path, default=None):
  return tax_policy.nested_get(value, path, default)


def getEUCountryCodes():
  return tax_policy.resolve_eu_country_codes(company_config=config.company)


def normalizeCountryCode(code):
  return tax_policy.normalize_country_code(code)


def isEUCountry(code):
  return tax_policy.is_eu_country(code, eu_country_codes=getEUCountryCodes())


def getCustomerTaxId(customer, eu_country_codes=None):
  eu_country_codes = tax_policy.resolve_eu_country_codes(
    company_config=config.company, eu_country_codes=eu_country_codes)
  tax_ids = _obj_get(customer, "tax_ids")
  if tax_ids is not None:
    return tax_policy.find_eu_vat_id(tax_ids, eu_country_codes=eu_country_codes)

  customer_id = _obj_get(customer, "id")
  if customer_id is None:
    return None

  cache_key = (customer_id, tuple(eu_country_codes))
  if cache_key in tax_ids_cached:
    return tax_ids_cached[cache_key]

  ids = stripe.Customer.list_tax_ids(customer_id, limit=10).data
  tax_id = tax_policy.find_eu_vat_id(ids, eu_country_codes=eu_country_codes)
  tax_ids_cached[cache_key] = tax_id
  return tax_id


def getInvoiceTaxId(invoice, eu_country_codes=None):
  eu_country_codes = tax_policy.resolve_eu_country_codes(
    company_config=config.company, eu_country_codes=eu_country_codes)
  return tax_policy.get_invoice_tax_id(invoice, eu_country_codes=eu_country_codes)


def resolveCustomerCountry(customer, invoice=None):
  return tax_policy.resolve_customer_country(
    customer, invoice=invoice, retrieve_customer_by_id=retrieveCustomer)


def getTaxClassificationWarning(tax_classification):
  return tax_policy.get_tax_classification_warning(tax_classification)


def classifyTaxTreatment(country, invoice_tax, merchant_country, has_eu_vat_id, eu_country_codes=None):
  eu_country_codes = tax_policy.resolve_eu_country_codes(
    company_config=config.company, eu_country_codes=eu_country_codes)
  return tax_policy.classify_tax_treatment(
    country=country,
    invoice_tax=invoice_tax,
    merchant_country=merchant_country,
    has_eu_vat_id=has_eu_vat_id,
    eu_country_codes=eu_country_codes,
  )


def classifyInvoiceTaxTreatment(customer, invoice=None, checkout_session=None, merchant_country=None, eu_country_codes=None):
  merchant_country = normalizeCountryCode(merchant_country)
  if merchant_country is None:
    merchant_country = normalizeCountryCode(config.company.get("country", "DE")) or "DE"

  eu_country_codes = tax_policy.resolve_eu_country_codes(
    company_config=config.company, eu_country_codes=eu_country_codes)

  def get_customer_tax_id_local(cus):
    return getCustomerTaxId(cus, eu_country_codes=eu_country_codes)

  return tax_policy.classify_invoice_tax_treatment(
    customer,
    get_customer_tax_id=get_customer_tax_id_local,
    invoice=invoice,
    checkout_session=checkout_session,
    merchant_country=merchant_country,
    eu_country_codes=eu_country_codes,
    retrieve_customer_by_id=retrieveCustomer,
  )


def _account_value(key, fallback_key=None, default=""):
  if key in config.accounts:
    return str(config.accounts[key])
  if fallback_key and fallback_key in config.accounts:
    return str(config.accounts[fallback_key])
  return str(default)


def getAccountingProps(customer, invoice=None, checkout_session=None):
  eu_country_codes = getEUCountryCodes()
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
    eu_country_codes=eu_country_codes,
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
  info = tax_context.get("info")
  if warning or info:
    invoice_or_session_id = "n/a"
    if invoice is not None:
      invoice_or_session_id = _obj_get(invoice, "id", "n/a")
    elif checkout_session is not None:
      invoice_or_session_id = _obj_get(checkout_session, "id", "n/a")
    if warning:
      print("Warning: {} {} {}".format(
        warning, _obj_get(customer, "id", "n/a"), invoice_or_session_id))
    if info:
      print("Info: {} {} {}".format(
        info, _obj_get(customer, "id", "n/a"), invoice_or_session_id))

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
