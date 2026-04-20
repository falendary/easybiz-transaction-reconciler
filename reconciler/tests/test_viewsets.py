from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from reconciler.models import Invoice, Match, Transaction
from reconciler.tests.fixtures import make_currency, make_customer, make_ingestion_event, make_source


class HealthCheckTest(TestCase):
    def test_returns_ok(self):
        resp = self.client.get(reverse("health"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class CurrencyViewSetTest(TestCase):
    def test_list_returns_200(self):
        resp = self.client.get("/api/currencies/")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)


class CustomerViewSetTest(TestCase):
    def setUp(self):
        self.customer = make_customer("CUST-V01", "Viewset Test Client")

    def test_list_returns_customer(self):
        resp = self.client.get("/api/customers/")
        self.assertEqual(resp.status_code, 200)
        ids = [c["customer_id"] for c in resp.json()]
        self.assertIn("CUST-V01", ids)

    def test_detail_returns_customer(self):
        resp = self.client.get(f"/api/customers/{self.customer.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["customer_id"], "CUST-V01")

    def test_detail_includes_reconciliation_balance(self):
        resp = self.client.get(f"/api/customers/{self.customer.pk}/")
        self.assertIn("reconciliation_balance", resp.json())


class InvoiceViewSetTest(TestCase):
    def setUp(self):
        self.invoice = Invoice.objects.create(
            invoice_id="INV-V-001",
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

    def test_list_returns_200(self):
        resp = self.client.get("/api/invoices/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_returns_line_items_and_matches(self):
        resp = self.client.get(f"/api/invoices/{self.invoice.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("line_items", data)
        self.assertIn("matches", data)

    def test_filter_by_status(self):
        resp = self.client.get("/api/invoices/?status=open")
        self.assertEqual(resp.status_code, 200)
        statuses = [i["status"] for i in resp.json()]
        self.assertTrue(all(s == "open" for s in statuses))


class TransactionViewSetTest(TestCase):
    def setUp(self):
        self.txn = Transaction.objects.create(
            transaction_id="TXN-V-001",
            date="2026-02-26",
            amount=Decimal("117.00"),
            currency=make_currency(),
            raw_counterparty="Test Client",
            ingestion_event=make_ingestion_event(),
        )

    def test_list_returns_200(self):
        resp = self.client.get("/api/transactions/")
        self.assertEqual(resp.status_code, 200)

    def test_detail_returns_payout_lines_and_matches(self):
        resp = self.client.get(f"/api/transactions/{self.txn.pk}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("payout_lines", data)
        self.assertIn("matches", data)

    def test_filter_by_reconciliation_status(self):
        resp = self.client.get("/api/transactions/?reconciliation_status=unprocessed")
        self.assertEqual(resp.status_code, 200)


class MatchViewSetTest(TestCase):
    def setUp(self):
        currency = make_currency()
        event = make_ingestion_event()
        source = make_source()
        customer = make_customer()
        invoice = Invoice.objects.create(
            invoice_id="INV-M-001",
            type="invoice",
            customer=customer,
            issue_date="2026-02-01",
            due_date="2026-03-01",
            currency=currency,
            subtotal=Decimal("100.00"),
            tax_total=Decimal("17.00"),
            total=Decimal("117.00"),
            status="open",
            source=source,
            ingestion_event=event,
        )
        txn = Transaction.objects.create(
            transaction_id="TXN-M-001",
            date="2026-02-26",
            amount=Decimal("117.00"),
            currency=currency,
            raw_counterparty="Test",
            ingestion_event=event,
        )
        self.match = Match.objects.create(
            transaction=txn,
            invoice=invoice,
            allocated_amount=Decimal("117.00"),
            confidence_score=Decimal("0.95"),
            match_type="exact",
            status="auto_matched",
        )

    def test_list_returns_200(self):
        resp = self.client.get("/api/matches/")
        self.assertEqual(resp.status_code, 200)

    def test_filter_by_status(self):
        resp = self.client.get("/api/matches/?status=auto_matched")
        self.assertEqual(resp.status_code, 200)
        statuses = [m["status"] for m in resp.json()]
        self.assertTrue(all(s == "auto_matched" for s in statuses))

    def test_detail_returns_200(self):
        resp = self.client.get(f"/api/matches/{self.match.pk}/")
        self.assertEqual(resp.status_code, 200)
