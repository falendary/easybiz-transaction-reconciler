from decimal import Decimal

from django.test import TestCase

from reconciler.models import Invoice, Transaction
from reconciler.serializers import (
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    ReconciliationRunSerializer,
    TransactionListSerializer,
)
from reconciler.tests.fixtures import make_currency, make_customer, make_ingestion_event, make_source


class InvoiceListSerializerTest(TestCase):
    def setUp(self):
        self.invoice = Invoice.objects.create(
            invoice_id="INV-SER-001",
            type="invoice",
            customer=make_customer(),
            issue_date="2026-02-01",
            due_date="2026-03-01",
            currency=make_currency(),
            subtotal=Decimal("100.00"),
            tax_total=Decimal("17.00"),
            total=Decimal("117.00"),
            status="open",
            source=make_source(),
            ingestion_event=make_ingestion_event(),
        )

    def test_contains_expected_fields(self):
        data = InvoiceListSerializer(self.invoice).data
        for field in ["id", "invoice_id", "type", "customer", "total", "status"]:
            self.assertIn(field, data)

    def test_does_not_contain_line_items_or_matches(self):
        data = InvoiceListSerializer(self.invoice).data
        self.assertNotIn("line_items", data)
        self.assertNotIn("matches", data)

    def test_detail_serializer_contains_line_items_and_matches(self):
        data = InvoiceDetailSerializer(self.invoice).data
        self.assertIn("line_items", data)
        self.assertIn("matches", data)

    def test_total_is_string_decimal(self):
        data = InvoiceListSerializer(self.invoice).data
        self.assertEqual(data["total"], "117.00")


class TransactionListSerializerTest(TestCase):
    def setUp(self):
        self.txn = Transaction.objects.create(
            transaction_id="TXN-SER-001",
            date="2026-02-26",
            amount=Decimal("117.00"),
            currency=make_currency(),
            raw_counterparty="Test Client",
            ingestion_event=make_ingestion_event(),
        )

    def test_contains_expected_fields(self):
        data = TransactionListSerializer(self.txn).data
        for field in ["id", "transaction_id", "date", "amount", "reconciliation_status", "is_duplicate"]:
            self.assertIn(field, data)

    def test_amount_is_string_decimal(self):
        data = TransactionListSerializer(self.txn).data
        self.assertEqual(data["amount"], "117.00")

    def test_default_reconciliation_status_is_unprocessed(self):
        data = TransactionListSerializer(self.txn).data
        self.assertEqual(data["reconciliation_status"], "unprocessed")


class ReconciliationRunSerializerTest(TestCase):
    def test_all_count_fields_present(self):
        from reconciler.models import ReconciliationRun
        run = ReconciliationRun.objects.create(
            status="completed",
            total_processed=80,
            auto_matched_count=60,
            needs_review_count=15,
            skipped_locked_count=5,
        )
        data = ReconciliationRunSerializer(run).data
        for field in ["total_processed", "auto_matched_count", "needs_review_count", "skipped_locked_count"]:
            self.assertIn(field, data)
