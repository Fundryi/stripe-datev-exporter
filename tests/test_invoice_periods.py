import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from stripe_datev import invoices
from stripe_datev import config


class InvoicePeriodRecognitionTest(unittest.TestCase):

  def _invoice(self, invoice_id="in_test", created_ts=1718729226):
    return SimpleNamespace(id=invoice_id, created=created_ts)

  def test_point_in_time_period_is_treated_as_known(self):
    invoice = self._invoice()
    line_item = {
      "description": "Payment for Invoice #11565",
      "period": {
        "start": 1718729226,
        "end": 1718729226,
      },
    }

    with patch("builtins.print") as mock_print:
      start, end = invoices.getLineItemRecognitionRange(line_item, invoice)

    expected = datetime.fromtimestamp(
      1718729226, timezone.utc).astimezone(config.accounting_tz)
    self.assertEqual(start, expected)
    self.assertEqual(end, expected)
    self.assertFalse(
      any("unknown period for line item" in " ".join(map(str, call.args))
          for call in mock_print.call_args_list)
    )

  def test_missing_period_warns_and_falls_back_to_created(self):
    invoice = self._invoice(invoice_id="in_missing_period", created_ts=1718729226)
    line_item = {
      "description": "No period in this description",
    }

    with patch("stripe_datev.invoices.dateparser.find_date_range", return_value=None):
      with patch("builtins.print") as mock_print:
        start, end = invoices.getLineItemRecognitionRange(line_item, invoice)

    expected = datetime.fromtimestamp(
      1718729226, timezone.utc).astimezone(config.accounting_tz)
    self.assertEqual(start, expected)
    self.assertEqual(end, expected)
    self.assertTrue(
      any("unknown period for line item" in " ".join(map(str, call.args))
          for call in mock_print.call_args_list)
    )


if __name__ == "__main__":
  unittest.main()
