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

  def test_pt_azores_excluded_territory_is_non_eu_outside_scope_with_info(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "PT"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 699,
        "customer_shipping": {"address": {"country": "PT"}},
        "total_taxes": [{"taxability_reason": "excluded_territory", "amount": 0}],
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIsNone(ctx["warning"])
    self.assertIsNotNone(ctx["info"])
    self.assertIn("excluded_territory", ctx["info"])
    self.assertTrue(ctx["excluded_territory"])

  def test_excluded_territory_signal_on_line_items(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "ES"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1000,
        "customer_shipping": {"address": {"country": "ES"}},
        "lines": {"data": [
          {"taxes": [{"taxability_reason": "excluded_territory", "amount": 0}]}
        ]},
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIsNone(ctx["warning"])
    self.assertIsNotNone(ctx["info"])

  def test_pt_not_supported_reason_is_non_eu_outside_scope_with_info(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "PT"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 699,
        "customer_shipping": {"address": {"country": "PT"}},
        "total_taxes": [{"taxability_reason": "not_supported", "amount": 0}],
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIsNone(ctx["warning"])
    self.assertIsNotNone(ctx["info"])
    self.assertIn("not_supported", ctx["info"])

  def test_es_canary_islands_by_postal_code_is_non_eu_outside_scope(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "ES", "postal_code": "35560"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 1529,
        "customer_address": {"country": "ES", "postal_code": "35560"},
        "total_taxes": [{"taxability_reason": "not_available", "amount": 0}],
      },
      merchant_country="DE",
    )
    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIsNone(ctx["warning"])
    self.assertIn("Canary Islands", ctx["info"])
    self.assertIn("35560", ctx["info"])

  def test_es_ceuta_postal_code(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "ES", "postal_code": "51001"}, "tax_ids": {"data": []}},
      invoice={"tax": 0, "total": 1000,
               "customer_address": {"country": "ES", "postal_code": "51001"}},
      merchant_country="DE",
    )
    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIn("Ceuta", ctx["info"])

  def test_pt_madeira_postal_code(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "PT", "postal_code": "9000-123"}, "tax_ids": {"data": []}},
      invoice={"tax": 0, "total": 1000,
               "customer_address": {"country": "PT", "postal_code": "9000-123"}},
      merchant_country="DE",
    )
    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIn("Madeira", ctx["info"])

  def test_pt_azores_postal_code(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "PT", "postal_code": "9700-193"}, "tax_ids": {"data": []}},
      invoice={"tax": 0, "total": 1000,
               "customer_address": {"country": "PT", "postal_code": "9700-193"}},
      merchant_country="DE",
    )
    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIn("Azores", ctx["info"])

  def test_es_mainland_postal_code_still_warns(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "ES", "postal_code": "28001"}, "tax_ids": {"data": []}},
      invoice={"tax": 0, "total": 1000,
               "customer_address": {"country": "ES", "postal_code": "28001"}},
      merchant_country="DE",
    )
    self.assertEqual(ctx["classification"], customer.TAX_CLASS_EU_B2C_MISSING_VAT_ID)
    self.assertEqual(ctx["warning"], customer.WARNING_EU_MISSING_VAT_ID)
    self.assertIsNone(ctx["info"])

  def test_non_eu_country_with_not_supported_reason_does_not_emit_info(self):
    ctx = customer.classifyInvoiceTaxTreatment(
      customer={"address": {"country": "AR"}, "tax_ids": {"data": []}},
      invoice={
        "tax": 0,
        "total": 899,
        "customer_shipping": {"address": {"country": "AR"}},
        "total_taxes": [{"taxability_reason": "not_supported", "amount": 0}],
      },
      merchant_country="DE",
    )

    self.assertEqual(ctx["classification"], customer.TAX_CLASS_NON_EU_OUTSIDE_SCOPE)
    self.assertIsNone(ctx["warning"])
    self.assertIsNone(ctx["info"])

  def test_eu_b2c_without_outside_scope_reason_still_warns(self):
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
    self.assertIsNone(ctx["info"])

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
