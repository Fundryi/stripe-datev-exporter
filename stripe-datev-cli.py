import decimal
from functools import reduce
import sys
import argparse
from datetime import datetime, timedelta, timezone
import datedelta
import stripe
import stripe_datev.invoices
import \
  stripe_datev.charges, \
  stripe_datev.customer, \
  stripe_datev.recognition, \
  stripe_datev.output, \
  stripe_datev.config, \
  stripe_datev.balance
import os
import os.path
import dotenv
import pytz
from stripe_datev_local import output_layout
from stripe_datev_local import downloads
from stripe_datev_local import datev_validation
from stripe_datev_local import run_logging

dotenv.load_dotenv(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".env"))

if "STRIPE_API_KEY" not in os.environ:
  print("Require STRIPE_API_KEY environment variable to be set")
  sys.exit(1)

stripe.api_key = os.environ["STRIPE_API_KEY"]
stripe.api_version = "2020-08-27"

out_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'out')
if stripe.api_key.startswith("sk_test"):
  out_dir = os.path.join(out_dir, "test")
if not os.path.exists(out_dir):
  os.mkdir(out_dir)


class StripeDatevCli(object):

  def run(self, argv):
    parser = argparse.ArgumentParser(
      description='Stripe utility',
    )
    parser.add_argument('command', type=str, help='Subcommand to run', choices=[
      'download',
      'validate_customers',
      'validate_exports',
      'fill_account_numbers',
      'clear_account_numbers',
      'list_accounts',
      'opos',
      'fees',
      'preview'
    ])

    args = parser.parse_args(argv[1:2])
    getattr(self, args.command)(argv[2:])

  def download(self, argv):
    parser = argparse.ArgumentParser(prog="stripe-datev-cli.py download")
    parser.add_argument('year', type=int, help='year to download data for')
    parser.add_argument('month', type=int, help='month to download data for')
    parser.add_argument('--pdf-workers', type=int, default=int(stripe_datev.config.download.get("pdf_workers", 23)),
                        help='parallel workers for PDF/receipt downloads (1-24, default from config.download.pdf_workers)')
    parser.add_argument('--pdf-max-rps', type=int, default=int(stripe_datev.config.download.get("pdf_max_rps", 23)),
                        help='max PDF/receipt HTTP requests per second (0 disables throttle, default from config.download.pdf_max_rps)')
    parser.add_argument('--pdf-timeout', type=int, default=int(stripe_datev.config.download.get("pdf_timeout", 30)),
                        help='HTTP timeout seconds for PDF/receipt downloads (default from config.download.pdf_timeout)')
    parser.add_argument('--pdf-retries', type=int, default=int(stripe_datev.config.download.get("pdf_retries", 4)),
                        help='retries for transient PDF/receipt download failures (default from config.download.pdf_retries)')
    parser.set_defaults(skip_historical_warnings=bool(
      stripe_datev.config.download.get("skip_historical_warnings", True)))
    parser.add_argument('--skip-historical-warnings', dest='skip_historical_warnings', action='store_true',
                        help='skip cross-month warning scan for earlier invoice changes and credit notes')
    parser.add_argument('--include-historical-warnings', dest='skip_historical_warnings', action='store_false',
                        help='force-enable cross-month warning scan even if config defaults to skip')
    parser.set_defaults(skip_receipts=bool(
      stripe_datev.config.download.get("skip_receipts", False)))
    parser.add_argument('--skip-receipts', dest='skip_receipts', action='store_true',
                        help='skip Stripe payment receipt (HTML) downloads — only invoice PDFs')
    parser.add_argument('--include-receipts', dest='skip_receipts', action='store_false',
                        help='force-enable receipt downloads even if config defaults to skip')

    args = parser.parse_args(argv)

    year = int(args.year)
    month = int(args.month)

    run_root = output_layout.resolve_download_root(out_dir, year, month)
    logs_dir = os.path.join(run_root, "logs")

    with run_logging.tee_run_log(logs_dir):
      self._download_body(args, year, month)

  def _download_body(self, args, year, month):
    if month > 0:
      fromTime = stripe_datev.config.accounting_tz.localize(
        datetime(year, month, 1, 0, 0, 0, 0))
      toTime = stripe_datev.config.accounting_tz.localize(
        datetime(year, month + 1, 1, 0, 0, 0, 0) if month <= 11 else datetime(year + 1, 1, 1, 0, 0, 0, 0))
    else:
      fromTime = stripe_datev.config.accounting_tz.localize(
        datetime(year, 1, 1, 0, 0, 0, 0))
      toTime = stripe_datev.config.accounting_tz.localize(
        datetime(year + 1, 1, 1, 0, 0, 0, 0))
    print("Retrieving data between {} and {} (inclusive, {})".format(fromTime.strftime(
      "%Y-%m-%d"), (toTime - timedelta(0, 1)).strftime("%Y-%m-%d"), stripe_datev.config.accounting_tz))
    thisMonth = fromTime.astimezone(
      stripe_datev.config.accounting_tz).strftime("%Y-%m")
    run_label = output_layout.period_label(year, month)
    output_dirs = output_layout.ensure_download_dirs(out_dir, year, month)
    print("Output root {}".format(os.path.relpath(output_dirs["root"], os.getcwd())))

    invoices = list(
      reversed(list(stripe_datev.invoices.listFinalizedInvoices(fromTime, toTime))))
    print("Retrieved {} invoice(s), total {} EUR".format(
      len(invoices), sum([decimal.Decimal(i.total) / 100 for i in invoices])))

    revenue_items = stripe_datev.invoices.createRevenueItems(invoices)

    balance_transactions = list(reversed(list(stripe_datev.balance.listBalanceTransactions(
      fromTime, toTime))))
    charges = stripe_datev.balance.extractCharges(balance_transactions)
    print("Retrieved {} balance transaction(s), {} charge(s), total {} EUR".format(len(
      balance_transactions), len(charges), sum([decimal.Decimal(charge.amount) / 100 for charge in charges])))

    direct_charges = list(filter(
      lambda charge: not stripe_datev.charges.chargeHasInvoice(charge), charges))
    revenue_items += stripe_datev.charges.createRevenueItems(direct_charges)

    overview_dir = output_dirs["overview"]
    with open(os.path.join(overview_dir, "overview-{}.csv".format(run_label)), "w", encoding="utf-8") as fp:
      fp.write(stripe_datev.invoices.to_csv(invoices))
      print("Wrote {} invoices      to {}".format(
        str(len(invoices)).rjust(4, " "), os.path.relpath(fp.name, os.getcwd())))

    monthly_recognition_dir = output_dirs["monthly_recognition"]
    with open(os.path.join(monthly_recognition_dir, "monthly_recognition-{}.csv".format(run_label)), "w", encoding="utf-8") as fp:
      fp.write(stripe_datev.invoices.to_recognized_month_csv2(revenue_items))
      print("Wrote {} revenue items to {}".format(
        str(len(revenue_items)).rjust(4, " "), os.path.relpath(fp.name, os.getcwd())))

    datevDir = output_dirs["datev"]

    # Datev Revenue

    records = []
    for revenue_item in revenue_items:
      records += stripe_datev.invoices.createAccountingRecords(revenue_item)

    records_by_month = {}
    for record in records:
      record_month = record["date"].strftime("%Y-%m")
      records_by_month[record_month] = records_by_month.get(record_month, []) + [record]

    for record_month, month_records in records_by_month.items():
      if month > 0:
        if record_month == thisMonth:
          name = "EXTF_{}_Revenue.csv".format(thisMonth)
        else:
          name = "EXTF_{}_Revenue_From_{}.csv".format(record_month, thisMonth)
        bezeichnung = "Stripe Revenue {} from {}".format(record_month, thisMonth)
      else:
        name = "EXTF_{}_Revenue.csv".format(record_month)
        bezeichnung = "Stripe Revenue {}".format(record_month)
      stripe_datev.output.writeRecords(os.path.join(
        datevDir, name), month_records, bezeichung=bezeichnung)

    # Datev Balance

    balance_records = stripe_datev.balance.createAccountingRecords(
      balance_transactions)

    balance_label = thisMonth if month > 0 else run_label
    stripe_datev.output.writeRecords(os.path.join(datevDir, "EXTF_{}_Balance.csv".format(
      balance_label)), balance_records, bezeichung="Stripe Balance {}".format(balance_label))

    # Invoices (PDF) + Receipts (HTML)

    invoicesDir = output_dirs["invoices"]
    receiptsDir = output_dirs["receipts"]
    invoicesLegacy = [output_dirs["invoices_legacy_flat"], output_dirs["pdf_legacy"]]
    receiptsLegacy = [output_dirs["receipts_legacy_flat"], output_dirs["pdf_legacy"]]

    pdf_jobs = []
    pdf_skipped_existing = 0
    pdf_skipped_missing_link = 0

    for invoice in invoices:
      pdfLink = invoice.invoice_pdf
      finalized_date = datetime.fromtimestamp(
        invoice.status_transitions.finalized_at, timezone.utc).astimezone(stripe_datev.config.accounting_tz)
      invNo = invoice.number

      fileName = "{} {}.pdf".format(finalized_date.strftime("%Y-%m-%d"), invNo)
      filePath, legacyPaths = output_layout.resolve_document_paths(
        invoicesDir, invoicesLegacy, fileName, finalized_date)
      if output_layout.file_exists(filePath, legacyPaths):
        pdf_skipped_existing += 1
        continue

      if not pdfLink:
        pdf_skipped_missing_link += 1
        continue
      pdf_jobs.append({
        "url": pdfLink,
        "file_path": filePath,
      })

    if not args.skip_receipts:
      for charge in charges + list(map(lambda tx: tx["source"]["destination_payment"], filter(lambda tx: tx["type"] == "transfer", balance_transactions))):
        if charge is None:
          continue
        created = datetime.fromtimestamp(charge.created, timezone.utc)
        fileName = "{} {}.html".format(
          created.strftime("%Y-%m-%d"), charge.receipt_number or charge.id)
        filePath, legacyPaths = output_layout.resolve_document_paths(
          receiptsDir, receiptsLegacy, fileName, created)
        if output_layout.file_exists(filePath, legacyPaths):
          pdf_skipped_existing += 1
          continue

        pdfLink = charge["receipt_url"]
        if not pdfLink:
          pdf_skipped_missing_link += 1
          continue
        pdf_jobs.append({
          "url": pdfLink,
          "file_path": filePath,
        })
    else:
      print("Skipping Stripe payment receipt (HTML) downloads (--skip-receipts)")

    pdf_workers = downloads.bounded_workers(args.pdf_workers, default_workers=3)
    print("PDF download queue: {} file(s), skipped existing {}, skipped missing link {}, workers {}, max_rps {}, timeout {}s, retries {}".format(
      len(pdf_jobs),
      pdf_skipped_existing,
      pdf_skipped_missing_link,
      pdf_workers,
      max(0, int(args.pdf_max_rps)),
      args.pdf_timeout,
      args.pdf_retries,
    ))
    download_result = downloads.download_many(
      pdf_jobs,
      workers=pdf_workers,
      max_requests_per_second=max(0, int(args.pdf_max_rps)),
      timeout_seconds=args.pdf_timeout,
      max_retries=max(0, int(args.pdf_retries)),
      progress_every=100,
    )
    if download_result["failed"] > 0:
      print("Warning: {} PDF/receipt download(s) failed".format(
        download_result["failed"]))

    # Warnings about changes to earlier invoices

    if args.skip_historical_warnings:
      print("Skipping historical cross-month warning scan (--skip-historical-warnings)")
    else:
      for status in ["uncollectible", "void"]:
        for invoice in stripe.Invoice.list(
            created={
                "lt": int(fromTime.timestamp()),
                "gte": int((fromTime - 24 * datedelta.MONTH).timestamp()),
            },
            status=status,
        ).auto_paging_iter():
          if (invoice.status_transitions.voided_at and datetime.fromtimestamp(
            invoice.status_transitions.voided_at, timezone.utc) >= fromTime and datetime.fromtimestamp(
            invoice.status_transitions.voided_at, timezone.utc) < toTime) or (invoice.status_transitions.marked_uncollectible_at and datetime.fromtimestamp(
                invoice.status_transitions.marked_uncollectible_at, timezone.utc) >= fromTime and datetime.fromtimestamp(
                invoice.status_transitions.marked_uncollectible_at, timezone.utc) < toTime
            ):
            print("Warning: found earlier invoice {} changed status to {} in this month, consider downloading {} again".format(invoice.id, status, datetime.fromtimestamp(
                invoice.status_transitions.finalized_at, timezone.utc).astimezone(stripe_datev.config.accounting_tz).strftime("%Y-%m")))

      for creditNote in stripe.CreditNote.list(
          created={
            "gte": int(fromTime.timestamp()),
            "lt": int(toTime.timestamp()),
          },
          expand=["data.invoice"]
      ).auto_paging_iter():
        invoiceFinalized = datetime.fromtimestamp(
          creditNote.invoice.status_transitions.finalized_at, timezone.utc).astimezone(stripe_datev.config.accounting_tz)
        if invoiceFinalized < fromTime:
          print("Warning: found credit note {} for earlier invoice, consider downloading {} again".format(
            creditNote.number, invoiceFinalized.strftime("%Y-%m")))

  def validate_exports(self, argv):
    parser = argparse.ArgumentParser(prog="stripe-datev-cli.py validate_exports")
    parser.add_argument('year', type=int, nargs='?',
                        help='year of the run folder, e.g. 2024')
    parser.add_argument('month', type=int, nargs='?',
                        help='month of the run folder, e.g. 6')
    parser.add_argument('--path', type=str,
                        help='explicit datev folder path to validate')

    args = parser.parse_args(argv)

    if args.path:
      datev_dir = args.path
    elif args.year is not None and args.month is not None:
      datev_dir = output_layout.resolve_datev_dir(out_dir, args.year, args.month)
      if not os.path.isdir(datev_dir):
        legacy_month_dir = os.path.join(
          output_layout.resolve_download_root(out_dir, args.year, args.month),
          "datev",
        )
        if os.path.isdir(legacy_month_dir):
          datev_dir = legacy_month_dir
    else:
      raise Exception("Provide either --path <datev_dir> or <year> <month>")

    if not os.path.isdir(datev_dir):
      raise Exception("DATEV export folder does not exist: {}".format(datev_dir))

    result = datev_validation.validate_datev_folder(datev_dir)
    print("Validated DATEV files in {}".format(os.path.relpath(datev_dir, os.getcwd())))
    print("Files checked: {}".format(result["files_checked"]))
    print("Rows checked: {}".format(result["rows_checked"]))
    print("Errors: {}".format(result["errors_count"]))
    if result["errors_count"] > 0:
      for err in result["errors"][:50]:
        print("Error:", err)
      if result["errors_count"] > 50:
        print("Error: {} additional issues suppressed".format(
          result["errors_count"] - 50))
      raise Exception("DATEV validation failed")
    print("DATEV validation passed")

  def validate_customers(self, argv):
    stripe_datev.customer.validate_customers()

  def fill_account_numbers(self, argv):
    stripe_datev.customer.fill_account_numbers()

  def clear_account_numbers(self, argv):
    stripe_datev.customer.clear_account_numbers()

  def list_accounts(self, argv):
    stripe_datev.customer.list_account_numbers(
      argv[0] if len(argv) > 0 else None)

  def opos(self, argv):
    if len(argv) > 0:
      ref = datetime(*list(map(int, argv))) + \
          timedelta(days=1) - timedelta(seconds=1)
      status = None
    else:
      ref = datetime.now()
      status = "open"
    ref = stripe_datev.config.accounting_tz.localize(ref)

    print("Unpaid invoices as of", ref)

    invoices = stripe.Invoice.list(
      created={
        "lte": int(ref.timestamp()),
        "gte": int((ref - datedelta.YEAR).timestamp()),
      },
      status=status,
      expand=["data.customer"]
    ).auto_paging_iter()

    totals = []
    for invoice in invoices:
      finalized_at = invoice.status_transitions.get("finalized_at", None)
      if finalized_at is None or datetime.fromtimestamp(finalized_at, tz=timezone.utc) > ref:
        continue
      marked_uncollectible_at = invoice.status_transitions.get(
        "marked_uncollectible_at", None)
      if marked_uncollectible_at is not None and datetime.fromtimestamp(marked_uncollectible_at, tz=timezone.utc) <= ref:
        continue
      voided_at = invoice.status_transitions.get("voided_at", None)
      if voided_at is not None and datetime.fromtimestamp(voided_at, tz=timezone.utc) <= ref:
        continue
      paid_at = invoice.status_transitions.get("paid_at", None)
      if paid_at is not None and datetime.fromtimestamp(paid_at, tz=timezone.utc) <= ref:
        continue

      customer = stripe_datev.customer.retrieveCustomer(invoice.customer)
      due_date = datetime.fromtimestamp(
        invoice.due_date if invoice.due_date else invoice.created, tz=timezone.utc)
      total = decimal.Decimal(invoice.total) / 100
      totals.append(total)
      print(invoice.number.ljust(13, " "), format(total, ",.2f").rjust(10, " "), "EUR", customer.email.ljust(
        35, " "), "due", due_date.date(), "({} overdue)".format(ref - due_date) if due_date < ref else "")

    total = reduce(lambda x, y: x + y, totals, decimal.Decimal(0))
    print("TOTAL        ", format(total, ",.2f").rjust(10, " "), "EUR")

  def fees(self, argv):
    parser = argparse.ArgumentParser(prog="stripe-datev-cli.py fees")
    parser.add_argument('year', type=int, help='year to download data for')
    parser.add_argument('month', type=int, help='month to download data for')

    args = parser.parse_args(argv)

    year = int(args.year)
    month = int(args.month)

    # Stripe invoices fees within the bounds of one UTC month
    fromTime = pytz.utc.localize(datetime(year, month, 1, 0, 0, 0, 0))
    toTime = pytz.utc.localize(
      datetime(year, month + 1, 1, 0, 0, 0, 0) if month <= 11 else datetime(year + 1, 1, 1, 0, 0, 0, 0))

    print("Retrieving data between {} and {} (inclusive, {})".format(fromTime.strftime(
      "%Y-%m-%d"), (toTime - timedelta(0, 1)).strftime("%Y-%m-%d"), timezone.utc))

    balance_transactions = list(reversed(list(stripe_datev.balance.listBalanceTransactions(
      fromTime, toTime))))
    print("Retrieved {} balance transaction(s)".format(len(balance_transactions)))

    records = stripe_datev.balance.createAccountingRecords(balance_transactions)

    feesTotal = 0
    contributionsTotal = 0

    for record in records:
      amount = decimal.Decimal(record["Umsatz (ohne Soll/Haben-Kz)"].replace(",", "."))
      if record["Konto"] == str(stripe_datev.config.accounts["stripe_fees"]):
        feesTotal += amount
      elif record["Konto"] == str(stripe_datev.config.accounts["contributions"]):
        contributionsTotal += amount

    print("Fees: {0:.2f} EUR".format(feesTotal))
    print("Contributions {0:.2f} EUR".format(contributionsTotal))

  def preview(self, argv):
    parser = argparse.ArgumentParser(prog="stripe-datev-cli.py preview")
    parser.add_argument(
      "object_id",
      type=str,
      help="Stripe object id (invoice in_..., charge ch_..., or balance transaction txn_...)",
    )
    args = parser.parse_args(argv)

    object_id = args.object_id
    if object_id.startswith("in_"):
      invoice = stripe_datev.invoices.retrieveInvoice(object_id)
      print("Previewing accounting records for invoice {} / {}".format(object_id, invoice["number"]))
      revenue_items = stripe_datev.invoices.createRevenueItems([invoice])
      records = []
      for revenue_item in revenue_items:
        records += stripe_datev.invoices.createAccountingRecords(revenue_item)
    elif object_id.startswith("ch_"):
      charge = stripe.Charge.retrieve(object_id)
      print("Previewing accounting records for charge {}".format(object_id))
      revenue_items = stripe_datev.charges.createRevenueItems([charge])
      records = []
      for revenue_item in revenue_items:
        records += stripe_datev.invoices.createAccountingRecords(revenue_item)
    elif object_id.startswith("txn_"):
      balance_transaction = stripe.BalanceTransaction.retrieve(object_id, expand=["source", "source.customer",
              "source.customer.tax_ids", "source.invoice", "source.charge",
              "source.charge.customer", "source.charge.invoice",
              "source.source_transaction", "source.source_transaction.invoice",
              "source.destination", "source.destination_payment"])
      print("Previewing accounting records for balance transaction {}".format(object_id))
      records = stripe_datev.balance.createAccountingRecords([balance_transaction])
    else:
      raise Exception("Unsupported object ID for preview: {}".format(object_id))

    records_by_month = {}
    for record in records:
      month = record["date"].strftime("%Y-%m")
      records_by_month[month] = records_by_month.get(month, []) + [record]

    for month in sorted(records_by_month.keys()):
      records = records_by_month[month]
      print()
      print(month)
      for record in sorted(records, key=lambda r: [r["date"], r["Belegfeld 1"], r["Konto"], r["Gegenkonto (ohne BU-Schlüssel)"]]):
        print(record['date'].strftime("%Y-%m-%d"), record['Umsatz (ohne Soll/Haben-Kz)'], record["Soll/Haben-Kennzeichen"], record['Konto'], record['Gegenkonto (ohne BU-Schlüssel)'], record.get("BU-Schlüssel", "-") or "-", '--', record['Buchungstext'])

if __name__ == '__main__':
  StripeDatevCli().run(sys.argv)
