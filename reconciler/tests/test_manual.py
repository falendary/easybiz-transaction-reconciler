"""Tests for manual intervention service functions and API endpoints."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from reconciler.models import Invoice, Match, Transaction
from reconciler.manual_service import (
    confirm_match,
    create_manual_match,
    force_close_invoice,
    mark_match_unrelated,
    reject_match,
    unlock_match,
)
from reconciler.tests.fixtures import (
    make_currency,
    make_customer,
    make_ingestion_event,
    make_source,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_invoice(invoice_id: str = "INV-2026-M001", total: str = "117.00") -> Invoice:
    return Invoice.objects.create(
        invoice_id=invoice_id,
        type="invoice",
        customer=make_customer(),
        issue_date="2026-02-01",
        due_date="2026-03-01",
        currency=make_currency(),
        subtotal=Decimal("100.00"),
        tax_total=Decimal("17.00"),
        total=Decimal(total),
        status="open",
        source=make_source(),
        ingestion_event=make_ingestion_event(),
    )


def make_transaction(
    transaction_id: str = "TXN-M001",
    amount: str = "117.00",
    recon_status: str = "needs_review",
) -> Transaction:
    return Transaction.objects.create(
        transaction_id=transaction_id,
        date="2026-02-26",
        amount=Decimal(amount),
        currency=make_currency(),
        raw_counterparty="Test Client",
        reconciliation_status=recon_status,
        ingestion_event=make_ingestion_event(),
    )


def make_match(
    txn: Transaction,
    invoice: Invoice,
    match_status: str = "needs_review",
    allocated: str = "117.00",
    locked: bool = False,
) -> Match:
    return Match.objects.create(
        transaction=txn,
        invoice=invoice,
        allocated_amount=Decimal(allocated),
        confidence_score=Decimal("0.70"),
        match_type="exact",
        status=match_status,
        locked_by_user=locked,
    )


# ---------------------------------------------------------------------------
# confirm_match
# ---------------------------------------------------------------------------

class ConfirmMatchServiceTest(TestCase):
    def setUp(self):
        self.inv = make_invoice()
        self.txn = make_transaction()
        self.match = make_match(self.txn, self.inv)

    def test_sets_status_confirmed_and_locks(self):
        confirm_match(self.match)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "confirmed")
        self.assertTrue(self.match.locked_by_user)
        self.assertIsNotNone(self.match.performed_at)

    def test_recomputes_invoice_status(self):
        confirm_match(self.match)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "paid")

    def test_updates_transaction_status(self):
        confirm_match(self.match)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.reconciliation_status, "auto_matched")

    def test_raises_if_already_rejected(self):
        self.match.status = "rejected"
        self.match.save()
        with self.assertRaises(ValueError):
            confirm_match(self.match)


# ---------------------------------------------------------------------------
# reject_match
# ---------------------------------------------------------------------------

class RejectMatchServiceTest(TestCase):
    def setUp(self):
        self.inv = make_invoice("INV-2026-M002")
        self.txn = make_transaction("TXN-M002")
        self.match = make_match(self.txn, self.inv)

    def test_sets_status_rejected_and_locks(self):
        reject_match(self.match)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "rejected")
        self.assertTrue(self.match.locked_by_user)

    def test_note_is_saved(self):
        reject_match(self.match, note="Wrong amount")
        self.match.refresh_from_db()
        self.assertEqual(self.match.note, "Wrong amount")

    def test_recomputes_invoice_to_open(self):
        reject_match(self.match)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "open")

    def test_updates_transaction_to_needs_review(self):
        reject_match(self.match)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.reconciliation_status, "needs_review")

    def test_raises_if_locked_confirmed(self):
        self.match.status = "confirmed"
        self.match.locked_by_user = True
        self.match.save()
        with self.assertRaises(ValueError):
            reject_match(self.match)


# ---------------------------------------------------------------------------
# mark_match_unrelated
# ---------------------------------------------------------------------------

class MarkUnrelatedServiceTest(TestCase):
    def setUp(self):
        self.inv = make_invoice("INV-2026-M003")
        self.txn = make_transaction("TXN-M003")
        self.match = make_match(self.txn, self.inv)

    def test_clears_invoice_and_sets_unrelated(self):
        mark_match_unrelated(self.match)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "unrelated")
        self.assertIsNone(self.match.invoice)

    def test_transaction_status_becomes_unrelated(self):
        mark_match_unrelated(self.match)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.reconciliation_status, "unrelated")


# ---------------------------------------------------------------------------
# unlock_match
# ---------------------------------------------------------------------------

class UnlockMatchServiceTest(TestCase):
    def test_clears_lock_and_performed_fields(self):
        inv = make_invoice("INV-2026-M004")
        txn = make_transaction("TXN-M004")
        match = make_match(txn, inv, match_status="confirmed", locked=True)
        unlock_match(match)
        match.refresh_from_db()
        self.assertFalse(match.locked_by_user)
        self.assertIsNone(match.performed_by)
        self.assertIsNone(match.performed_at)


# ---------------------------------------------------------------------------
# create_manual_match
# ---------------------------------------------------------------------------

class CreateManualMatchServiceTest(TestCase):
    def setUp(self):
        self.inv = make_invoice("INV-2026-M005", total="200.00")
        self.txn = make_transaction("TXN-M005", amount="200.00")

    def test_creates_match_with_correct_fields(self):
        match = create_manual_match(self.txn, self.inv, Decimal("200.00"), note="Manual")
        self.assertEqual(match.status, "manually_matched")
        self.assertEqual(match.match_type, "exact")
        self.assertTrue(match.locked_by_user)
        self.assertEqual(match.confidence_score, Decimal("1.0"))
        self.assertEqual(match.note, "Manual")

    def test_recomputes_invoice_to_paid(self):
        create_manual_match(self.txn, self.inv, Decimal("200.00"))
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "paid")

    def test_raises_on_over_allocation(self):
        with self.assertRaises(ValueError):
            create_manual_match(self.txn, self.inv, Decimal("201.00"))

    def test_partial_manual_match(self):
        create_manual_match(self.txn, self.inv, Decimal("100.00"))
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "partially_paid")


# ---------------------------------------------------------------------------
# force_close_invoice
# ---------------------------------------------------------------------------

class ForceCloseInvoiceServiceTest(TestCase):
    def test_sets_status_and_note(self):
        inv = make_invoice("INV-2026-M006")
        force_close_invoice(inv, note="Client bankrupt")
        inv.refresh_from_db()
        self.assertEqual(inv.status, "force_closed")
        self.assertEqual(inv.force_close_note, "Client bankrupt")
        self.assertIsNotNone(inv.force_closed_at)

    def test_raises_on_blank_note(self):
        inv = make_invoice("INV-2026-M007")
        with self.assertRaises(ValueError):
            force_close_invoice(inv, note="")

    def test_recompute_status_does_nothing_after_force_close(self):
        inv = make_invoice("INV-2026-M008")
        force_close_invoice(inv, note="Closed")
        inv.recompute_status()
        inv.refresh_from_db()
        self.assertEqual(inv.status, "force_closed")


# ---------------------------------------------------------------------------
# API: POST /api/matches/
# ---------------------------------------------------------------------------

class CreateManualMatchAPITest(TestCase):
    def setUp(self):
        self.inv = make_invoice("INV-2026-A001", total="100.00")
        self.txn = make_transaction("TXN-A001", amount="100.00")
        self.url = reverse("match-list")

    def test_creates_match_returns_201(self):
        resp = self.client.post(self.url, {
            "transaction": self.txn.pk,
            "invoice": self.inv.pk,
            "allocated_amount": "100.00",
        }, content_type="application/json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Match.objects.count(), 1)

    def test_over_allocation_returns_400(self):
        resp = self.client.post(self.url, {
            "transaction": self.txn.pk,
            "invoice": self.inv.pk,
            "allocated_amount": "200.00",
        }, content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_missing_fields_returns_400(self):
        resp = self.client.post(self.url, {"transaction": self.txn.pk}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# API: DELETE /api/matches/<id>/
# ---------------------------------------------------------------------------

class DeleteMatchAPITest(TestCase):
    def setUp(self):
        self.inv = make_invoice("INV-2026-A002")
        self.txn = make_transaction("TXN-A002")

    def test_delete_unlocked_match_returns_204(self):
        match = make_match(self.txn, self.inv, locked=False)
        url = reverse("match-detail", args=[match.pk])
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Match.objects.count(), 0)

    def test_delete_locked_match_returns_403(self):
        match = make_match(self.txn, self.inv, locked=True)
        url = reverse("match-detail", args=[match.pk])
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Match.objects.count(), 1)


# ---------------------------------------------------------------------------
# API: POST /api/matches/<id>/confirm/
# ---------------------------------------------------------------------------

class ConfirmMatchAPITest(TestCase):
    def test_confirm_returns_200(self):
        inv = make_invoice("INV-2026-A003")
        txn = make_transaction("TXN-A003")
        match = make_match(txn, inv)
        url = reverse("match-confirm", args=[match.pk])
        resp = self.client.post(url, {}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "confirmed")

    def test_confirm_rejected_match_returns_400(self):
        inv = make_invoice("INV-2026-A004")
        txn = make_transaction("TXN-A004")
        match = make_match(txn, inv, match_status="rejected")
        url = reverse("match-confirm", args=[match.pk])
        resp = self.client.post(url, {}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# API: POST /api/matches/<id>/reject/
# ---------------------------------------------------------------------------

class RejectMatchAPITest(TestCase):
    def test_reject_returns_200(self):
        inv = make_invoice("INV-2026-A005")
        txn = make_transaction("TXN-A005")
        match = make_match(txn, inv)
        url = reverse("match-reject", args=[match.pk])
        resp = self.client.post(url, {"note": "Incorrect amount"}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "rejected")


# ---------------------------------------------------------------------------
# API: POST /api/matches/<id>/mark-unrelated/
# ---------------------------------------------------------------------------

class MarkUnrelatedAPITest(TestCase):
    def test_mark_unrelated_returns_200(self):
        inv = make_invoice("INV-2026-A006")
        txn = make_transaction("TXN-A006")
        match = make_match(txn, inv)
        url = reverse("match-mark-unrelated", args=[match.pk])
        resp = self.client.post(url, {}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "unrelated")


# ---------------------------------------------------------------------------
# API: POST /api/matches/<id>/unlock/
# ---------------------------------------------------------------------------

class UnlockMatchAPITest(TestCase):
    def test_unlock_returns_200(self):
        inv = make_invoice("INV-2026-A007")
        txn = make_transaction("TXN-A007")
        match = make_match(txn, inv, match_status="confirmed", locked=True)
        url = reverse("match-unlock", args=[match.pk])
        resp = self.client.post(url, {}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["locked_by_user"])


# ---------------------------------------------------------------------------
# API: POST /api/invoices/<id>/force-close/
# ---------------------------------------------------------------------------

class ForceCloseInvoiceAPITest(TestCase):
    def setUp(self):
        self.inv = make_invoice("INV-2026-A008")
        self.url = reverse("invoice-force-close", args=[self.inv.pk])

    def test_force_close_returns_200(self):
        resp = self.client.post(self.url, {"note": "Client dispute resolved"}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "force_closed")

    def test_blank_note_returns_400(self):
        resp = self.client.post(self.url, {"note": ""}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_missing_note_returns_400(self):
        resp = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(resp.status_code, 400)
