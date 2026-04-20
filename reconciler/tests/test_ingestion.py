import json

from django.test import TestCase

from reconciler.models import IngestionEvent, Invoice, InvoiceLineItem, PayoutLine, Transaction
from reconciler.tests.fixtures import (
    CREDIT_NOTE_RECORD,
    DUPLICATE_TRANSACTION_RECORD,
    INVOICE_RECORD,
    PAYOUT_CSV,
    PAYOUT_TRANSACTION_RECORD,
    TRANSACTION_RECORD,
    upload,
)


class IngestInvoicesTest(TestCase):
    def test_happy_path_creates_invoice_and_customer(self):
        resp = upload(self.client, "ingest-invoices", json.dumps([INVOICE_RECORD]), "invoices.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["created"], 1)
        self.assertEqual(data["updated"], 0)
        self.assertTrue(Invoice.objects.filter(invoice_id="INV-TEST-0001").exists())
        self.assertEqual(InvoiceLineItem.objects.filter(invoice__invoice_id="INV-TEST-0001").count(), 1)

    def test_credit_note_ingested_correctly(self):
        resp = upload(self.client, "ingest-invoices", json.dumps([CREDIT_NOTE_RECORD]), "invoices.json")
        self.assertEqual(resp.status_code, 200)
        inv = Invoice.objects.get(invoice_id="CN-TEST-0001")
        self.assertEqual(inv.type, "credit_note")

    def test_re_upload_is_idempotent(self):
        payload = json.dumps([INVOICE_RECORD])
        upload(self.client, "ingest-invoices", payload, "invoices.json")
        resp = upload(self.client, "ingest-invoices", payload, "invoices.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["updated"], 1)
        self.assertEqual(Invoice.objects.filter(invoice_id="INV-TEST-0001").count(), 1)

    def test_ingestion_event_recorded_on_success(self):
        upload(self.client, "ingest-invoices", json.dumps([INVOICE_RECORD]), "invoices.json")
        event = IngestionEvent.objects.filter(file_type="invoices").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.status, "success")

    def test_malformed_json_returns_400(self):
        resp = upload(self.client, "ingest-invoices", "not-json", "invoices.json")
        self.assertEqual(resp.status_code, 400)

    def test_wrong_extension_returns_400(self):
        resp = upload(self.client, "ingest-invoices", json.dumps([INVOICE_RECORD]), "invoices.csv")
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_id_in_same_file_is_skipped(self):
        payload = json.dumps([INVOICE_RECORD, INVOICE_RECORD])
        resp = upload(self.client, "ingest-invoices", payload, "invoices.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["created"], 1)
        self.assertEqual(data["skipped"], 1)


class IngestTransactionsTest(TestCase):
    def test_happy_path_creates_transaction(self):
        resp = upload(self.client, "ingest-transactions", json.dumps([TRANSACTION_RECORD]), "transactions.json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["created"], 1)
        self.assertTrue(Transaction.objects.filter(transaction_id="TXN-TEST-0001").exists())

    def test_re_imported_prefix_sets_is_duplicate(self):
        resp = upload(
            self.client, "ingest-transactions",
            json.dumps([DUPLICATE_TRANSACTION_RECORD]), "transactions.json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["duplicates_flagged"], 1)
        self.assertTrue(Transaction.objects.get(transaction_id="TXN-TEST-0002").is_duplicate)

    def test_re_upload_is_idempotent(self):
        payload = json.dumps([TRANSACTION_RECORD])
        upload(self.client, "ingest-transactions", payload, "transactions.json")
        resp = upload(self.client, "ingest-transactions", payload, "transactions.json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["updated"], 1)
        self.assertEqual(Transaction.objects.filter(transaction_id="TXN-TEST-0001").count(), 1)

    def test_malformed_json_returns_400(self):
        resp = upload(self.client, "ingest-transactions", "{bad}", "transactions.json")
        self.assertEqual(resp.status_code, 400)


class IngestPayoutTest(TestCase):
    def setUp(self):
        upload(
            self.client, "ingest-transactions",
            json.dumps([PAYOUT_TRANSACTION_RECORD]), "transactions.json",
        )

    def test_happy_path_creates_payout_lines(self):
        resp = upload(self.client, "ingest-payout", PAYOUT_CSV, "payout_report.csv")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["payout_id"], "po_TESTPAYOUT")
        self.assertEqual(data["parent_transaction"], "TXN-PAYOUT-001")
        self.assertEqual(data["lines_created"], 1)
        self.assertTrue(PayoutLine.objects.filter(charge_id="ch_TEST1").exists())

    def test_re_upload_is_idempotent(self):
        upload(self.client, "ingest-payout", PAYOUT_CSV, "payout_report.csv")
        resp = upload(self.client, "ingest-payout", PAYOUT_CSV, "payout_report.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PayoutLine.objects.filter(charge_id="ch_TEST1").count(), 1)

    def test_missing_parent_transaction_returns_400(self):
        csv = (
            "charge_id,invoice_id,customer_name,gross_amount,fee,net_amount,type\n"
            "ch_X,,Client,100.00,3.00,97.00,charge\n"
            "po_UNKNOWN,,PAYOUT TOTAL,,,97.00,payout\n"
        )
        resp = upload(self.client, "ingest-payout", csv, "payout_report.csv")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No transaction found", resp.json()["detail"])

    def test_wrong_extension_returns_400(self):
        resp = upload(self.client, "ingest-payout", PAYOUT_CSV, "payout_report.json")
        self.assertEqual(resp.status_code, 400)
