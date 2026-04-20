from decimal import Decimal

from django.test import TestCase

from reconciler.models import (
    Account,
    Currency,
    Customer,
    FXRate,
    IngestionEvent,
    Invoice,
    Match,
    ReconciliationRun,
    Source,
    Transaction,
)
from reconciler.tests.fixtures import make_currency, make_customer, make_ingestion_event, make_source


class CurrencyModelTest(TestCase):
    def test_str(self):
        c = Currency(code="EUR", name="Euro", symbol="€", decimal_places=2)
        self.assertEqual(str(c), "EUR")


class SourceModelTest(TestCase):
    def test_str(self):
        s = Source(name="Stripe", source_type="payment_processor")
        self.assertEqual(str(s), "Stripe")


class CustomerModelTest(TestCase):
    def test_str(self):
        c = Customer(customer_id="CUST-001", name="Acme S.à r.l.")
        self.assertEqual(str(c), "CUST-001 — Acme S.à r.l.")


class FXRateModelTest(TestCase):
    def test_str(self):
        eur = Currency.objects.create(code="EUR", name="Euro", symbol="€", decimal_places=2)
        usd = Currency.objects.create(code="USD", name="US Dollar", symbol="$", decimal_places=2)
        fx = FXRate(base_currency=eur, quote_currency=usd, rate=Decimal("1.0850"), date="2026-02-28")
        self.assertIn("EUR/USD", str(fx))
        self.assertIn("1.0850", str(fx))


class InvoiceRecomputeStatusTest(TestCase):
    def setUp(self):
        self.currency = make_currency()
        self.source = make_source()
        self.event = make_ingestion_event()
        self.customer = make_customer()
        self.invoice = Invoice.objects.create(
            invoice_id="INV-S-001",
            type="invoice",
            customer=self.customer,
            issue_date="2026-02-01",
            due_date="2026-03-01",
            currency=self.currency,
            subtotal=Decimal("100.00"),
            tax_total=Decimal("17.00"),
            total=Decimal("117.00"),
            status="open",
            source=self.source,
            ingestion_event=self.event,
        )
        self.txn = Transaction.objects.create(
            transaction_id="TXN-S-001",
            date="2026-02-26",
            amount=Decimal("117.00"),
            currency=self.currency,
            raw_counterparty="Test",
            ingestion_event=self.event,
        )

    def _make_match(self, amount: str, status: str = "confirmed") -> Match:
        return Match.objects.create(
            transaction=self.txn,
            invoice=self.invoice,
            allocated_amount=Decimal(amount),
            confidence_score=Decimal("0.95"),
            match_type="exact",
            status=status,
        )

    def test_open_when_no_matches(self):
        self.invoice.recompute_status()
        self.assertEqual(self.invoice.status, "open")

    def test_paid_when_fully_allocated(self):
        self._make_match("117.00")
        self.invoice.recompute_status()
        self.assertEqual(self.invoice.status, "paid")

    def test_partially_paid_when_partially_allocated(self):
        self._make_match("50.00")
        self.invoice.recompute_status()
        self.assertEqual(self.invoice.status, "partially_paid")

    def test_rejected_match_does_not_count(self):
        self._make_match("117.00", status="rejected")
        self.invoice.recompute_status()
        self.assertEqual(self.invoice.status, "open")

    def test_force_closed_status_is_preserved(self):
        self.invoice.status = "force_closed"
        self.invoice.save()
        self.invoice.recompute_status()
        self.assertEqual(self.invoice.status, "force_closed")


class ReconciliationRunModelTest(TestCase):
    def test_str_contains_status(self):
        run = ReconciliationRun.objects.create(status="completed", total_processed=10)
        self.assertIn("completed", str(run))
