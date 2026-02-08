import unittest

from stripe_datev import customer


class TaxClassificationTest(unittest.TestCase):

  def test_us_invoice_zero_tax_no_vat_id_is_non_eu_outside_scope(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "US"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1000,
        "customer_shipping": {"address": {"country": "US"}},
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIsNone(ctx["warning"])

  def test_sa_invoice_zero_tax_no_vat_id_is_non_eu_outside_scope(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "SA"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1000,
        "customer_shipping": {"address": {"country": "SA"}},
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIsNone(ctx["warning"])

  def test_fr_invoice_zero_tax_with_vat_id_is_eu_reverse_charge(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "FR"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1000,
        "customer_shipping": {"address": {"country": "FR"}},
        "customer_tax_ids": [{"type": "eu_vat", "value": "FR123456789"}],
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_EU_REVERSE_CHARGE)
    self.assertIsNone(ctx["warning"])

  def test_fr_invoice_zero_tax_without_vat_id_is_eu_b2c_missing_vat_id(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "FR"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1000,
        "customer_shipping": {"address": {"country": "FR"}},
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_EU_B2C_MISSING_VAT_ID)
    self.assertEqual(ctx["warning"], customer.WARNING_EU_MISSING_VAT_ID)

  def test_missing_country_is_unknown_location(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1000,
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_UNKNOWN_LOCATION)
    self.assertEqual(ctx["warning"], customer.WARNING_UNKNOWN_LOCATION)

  def test_eu_country_list_can_be_overridden(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "SA"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1000,
      },
      merchant_country="DE",
      eu_country_codes=["SA", "DE"],
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_EU_B2C_MISSING_VAT_ID)
    self.assertEqual(ctx["warning"], customer.WARNING_EU_MISSING_VAT_ID)


if __name__ == "__main__":
  unittest.main()
