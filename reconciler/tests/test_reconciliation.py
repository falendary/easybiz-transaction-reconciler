"""Tests for the reconciliation engine (reconciliation_service.py) and ReconcileView."""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from reconciler.models import Invoice, Match, PayoutLine, ReconciliationRun, Transaction
from reconciler.reconciliation_service import run_reconciliation
from reconciler.tests.fixtures import (
    make_currency,
    make_customer,
    make_ingestion_event,
    make_source,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_invoice(
    invoice_id: str = "INV-2026-0001",
    total: str = "117.00",
    status: str = "open",
) -> Invoice:
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
        status=status,
        source=make_source(),
        ingestion_event=make_ingestion_event(),
    )


def make_transaction(
    transaction_id: str = "TXN-0001",
    amount: str = "117.00",
    structured_reference: str = "",
    description: str = "",
    raw_counterparty: str = "ACME Corp",
    is_duplicate: bool = False,
    locked_by_user: bool = False,
) -> Transaction:
    return Transaction.objects.create(
        transaction_id=transaction_id,
        date="2026-02-26",
        amount=Decimal(amount),
        currency=make_currency(),
        raw_counterparty=raw_counterparty,
        structured_reference=structured_reference or None,
        description=description or None,
        is_duplicate=is_duplicate,
        locked_by_user=locked_by_user,
        ingestion_event=make_ingestion_event(),
    )


# ---------------------------------------------------------------------------
# Rule 1 — Noise / negative amount
# ---------------------------------------------------------------------------

class Rule1NoiseTest(TestCase):
    def test_negative_amount_marked_unrelated(self):
        txn = make_transaction(transaction_id="TXN-NEG", amount="-50.00")
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "unrelated")
        match = Match.objects.get(transaction=txn)
        self.assertEqual(match.match_type, "noise")
        self.assertEqual(match.confidence_score, Decimal("1.0"))

    def test_noise_counterparty_marked_unrelated(self):
        txn = make_transaction(transaction_id="TXN-NOISE", raw_counterparty="PAYROLL JUNE")
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "unrelated")


# ---------------------------------------------------------------------------
# Rule 2 — Duplicate
# ---------------------------------------------------------------------------

class Rule2DuplicateTest(TestCase):
    def test_duplicate_flag_sets_status(self):
        txn = make_transaction(transaction_id="TXN-DUP", is_duplicate=True)
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "duplicate")
        match = Match.objects.get(transaction=txn)
        self.assertEqual(match.match_type, "duplicate")


# ---------------------------------------------------------------------------
# Rule 3 — Payout decomposition
# ---------------------------------------------------------------------------

class Rule3PayoutTest(TestCase):
    def test_payout_lines_create_matches(self):
        make_invoice(invoice_id="INV-2026-0001")
        txn = make_transaction(
            transaction_id="TXN-PO-001",
            amount="113.56",
            structured_reference="po_TESTPAYOUT",
            raw_counterparty="STRIPE PAYMENTS",
        )
        PayoutLine.objects.create(
            transaction=txn,
            charge_id="ch_TEST1",
            raw_invoice_id="INV-2026-0001",
            gross_amount=Decimal("117.00"),
            fee=Decimal("3.44"),
            net_amount=Decimal("113.56"),
            type="charge",
            customer_name="Test Client",
            ingestion_event=make_ingestion_event(),
        )
        run_reconciliation()
        txn.refresh_from_db()
        matches = Match.objects.filter(transaction=txn)
        self.assertEqual(matches.count(), 1)
        self.assertEqual(matches.first().match_type, "payout")

    def test_payout_line_missing_invoice_needs_review(self):
        txn = make_transaction(
            transaction_id="TXN-PO-002",
            amount="50.00",
            structured_reference="po_NOINVOICE",
        )
        PayoutLine.objects.create(
            transaction=txn,
            charge_id="ch_NOINV",
            raw_invoice_id="INV-9999-9999",
            gross_amount=Decimal("50.00"),
            fee=Decimal("0.00"),
            net_amount=Decimal("50.00"),
            type="charge",
            customer_name="Unknown",
            ingestion_event=make_ingestion_event(),
        )
        run_reconciliation()
        txn.refresh_from_db()
        match = Match.objects.get(transaction=txn)
        self.assertIsNone(match.invoice)
        self.assertEqual(match.status, "needs_review")


# ---------------------------------------------------------------------------
# Rule 4 — Exact match
# ---------------------------------------------------------------------------

class Rule4ExactTest(TestCase):
    def test_exact_reference_and_amount_auto_matched(self):
        make_invoice(invoice_id="INV-2026-0001", total="117.00")
        txn = make_transaction(
            transaction_id="TXN-EXACT",
            amount="117.00",
            structured_reference="INV-2026-0001",
        )
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "auto_matched")
        match = Match.objects.get(transaction=txn)
        self.assertEqual(match.match_type, "exact")
        self.assertEqual(match.confidence_score, Decimal("0.95"))

    def test_no_separator_id_normalised(self):
        make_invoice(invoice_id="INV-2026-0002", total="100.00")
        txn = make_transaction(
            transaction_id="TXN-NOSEP",
            amount="100.00",
            structured_reference="INV20260002",
        )
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "auto_matched")


# ---------------------------------------------------------------------------
# Rule 5 — FX tolerance
# ---------------------------------------------------------------------------

class Rule5FXTest(TestCase):
    def test_amount_within_2pct_auto_matched(self):
        make_invoice(invoice_id="INV-2026-0003", total="117.00")
        txn = make_transaction(
            transaction_id="TXN-FX",
            amount="116.00",  # ~0.85% diff
            structured_reference="INV-2026-0003",
        )
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "auto_matched")
        match = Match.objects.get(transaction=txn)
        self.assertEqual(match.match_type, "fx")

    def test_amount_outside_tolerance_not_matched_by_rule5(self):
        make_invoice(invoice_id="INV-2026-0004", total="117.00")
        txn = make_transaction(
            transaction_id="TXN-FX-OVER",
            amount="80.00",  # >2% diff, no exact match → falls through to partial or no-match
            structured_reference="INV-2026-0004",
        )
        run_reconciliation()
        match = Match.objects.get(transaction=txn)
        self.assertNotEqual(match.match_type, "fx")


# ---------------------------------------------------------------------------
# Rule 6 — Consolidated payment
# ---------------------------------------------------------------------------

class Rule6ConsolidatedTest(TestCase):
    def test_multiple_ids_in_description_split_proportionally(self):
        make_invoice(invoice_id="INV-2026-0010", total="100.00")
        make_invoice(invoice_id="INV-2026-0011", total="200.00")
        txn = make_transaction(
            transaction_id="TXN-CONS",
            amount="300.00",
            description="Payment for INV-2026-0010 and INV-2026-0011",
        )
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "needs_review")
        matches = Match.objects.filter(transaction=txn)
        self.assertEqual(matches.count(), 2)
        self.assertTrue(all(m.match_type == "consolidated" for m in matches))
        total_allocated = sum(m.allocated_amount for m in matches)
        self.assertEqual(total_allocated, Decimal("300.00"))


# ---------------------------------------------------------------------------
# Rule 7 — Partial payment
# ---------------------------------------------------------------------------

class Rule7PartialTest(TestCase):
    def test_partial_amount_needs_review(self):
        make_invoice(invoice_id="INV-2026-0020", total="200.00")
        txn = make_transaction(
            transaction_id="TXN-PART",
            amount="100.00",
            structured_reference="INV-2026-0020",
        )
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "needs_review")
        match = Match.objects.get(transaction=txn)
        self.assertEqual(match.match_type, "partial")
        self.assertEqual(match.confidence_score, Decimal("0.75"))


# ---------------------------------------------------------------------------
# Rule 8 — Fuzzy match
# ---------------------------------------------------------------------------

class Rule8FuzzyTest(TestCase):
    def test_invoice_id_extracted_from_description(self):
        make_invoice(invoice_id="INV-2026-0030", total="117.00")
        txn = make_transaction(
            transaction_id="TXN-FUZZY",
            amount="117.00",
            description="Wire transfer re INV-2026-0030 thank you",
        )
        run_reconciliation()
        txn.refresh_from_db()
        match = Match.objects.get(transaction=txn)
        self.assertIsNotNone(match.invoice)
        self.assertEqual(match.invoice.invoice_id, "INV-2026-0030")


# ---------------------------------------------------------------------------
# Rule 10 — No match
# ---------------------------------------------------------------------------

class Rule10NoMatchTest(TestCase):
    def test_unresolvable_transaction_needs_review(self):
        txn = make_transaction(
            transaction_id="TXN-UNKNOWN",
            amount="999.99",
            raw_counterparty="Mystery Corp",
        )
        run_reconciliation()
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "needs_review")
        match = Match.objects.get(transaction=txn)
        self.assertIsNone(match.invoice)
        self.assertEqual(match.confidence_score, Decimal("0.0"))


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class IdempotencyTest(TestCase):
    def test_running_twice_produces_same_match_count(self):
        make_invoice(invoice_id="INV-2026-0040", total="117.00")
        make_transaction(
            transaction_id="TXN-IDEM",
            amount="117.00",
            structured_reference="INV-2026-0040",
        )
        run_reconciliation()
        count_after_first = Match.objects.count()
        run_reconciliation()
        count_after_second = Match.objects.count()
        self.assertEqual(count_after_first, count_after_second)


# ---------------------------------------------------------------------------
# Locked transactions
# ---------------------------------------------------------------------------

class LockedTransactionTest(TestCase):
    def test_locked_transaction_not_processed(self):
        txn = make_transaction(
            transaction_id="TXN-LOCKED",
            amount="117.00",
            locked_by_user=True,
        )
        run_reconciliation()
        self.assertEqual(Match.objects.filter(transaction=txn).count(), 0)
        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "unprocessed")

    def test_locked_run_counts_skipped(self):
        make_transaction(transaction_id="TXN-LOCK2", locked_by_user=True)
        run = run_reconciliation()
        self.assertEqual(run.skipped_locked_count, 1)


# ---------------------------------------------------------------------------
# ReconciliationRun record
# ---------------------------------------------------------------------------

class ReconciliationRunRecordTest(TestCase):
    def test_run_record_created_with_correct_counts(self):
        make_invoice(invoice_id="INV-2026-0050", total="117.00")
        make_transaction(
            transaction_id="TXN-RUN1",
            amount="117.00",
            structured_reference="INV-2026-0050",
        )
        make_transaction(transaction_id="TXN-RUN2", amount="999.00", raw_counterparty="Unknown")
        run = run_reconciliation()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.total_processed, 2)
        self.assertEqual(run.auto_matched_count, 1)
        self.assertEqual(run.needs_review_count, 1)
        self.assertIsNotNone(run.finished_at)


# ---------------------------------------------------------------------------
# POST /api/reconcile/ endpoint
# ---------------------------------------------------------------------------

class ReconcileViewTest(TestCase):
    def test_post_returns_200_with_run_summary(self):
        make_invoice(invoice_id="INV-2026-0060", total="117.00")
        make_transaction(
            transaction_id="TXN-VIEW1",
            amount="117.00",
            structured_reference="INV-2026-0060",
        )
        response = self.client.post(reverse("reconcile"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_processed", data)
        self.assertIn("auto_matched_count", data)
        self.assertEqual(data["status"], "completed")

    def test_post_creates_reconciliation_run_record(self):
        self.client.post(reverse("reconcile"))
        self.assertEqual(ReconciliationRun.objects.count(), 1)


# ---------------------------------------------------------------------------
# Rule 9 — AI fallback (mocked)
# ---------------------------------------------------------------------------

class Rule9AITest(TestCase):
    @patch("reconciler.claude_service.anthropic.Anthropic")
    def test_ai_rule_used_when_enabled(self, mock_anthropic_class):
        make_invoice(invoice_id="INV-2026-0070", total="117.00")
        txn = make_transaction(
            transaction_id="TXN-AI",
            amount="117.00",
            raw_counterparty="Totally Unrecognisable Payer",
        )

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps({
            "invoice_id": "INV-2026-0070",
            "confidence": 0.90,
            "note": "AI matched on amount and date proximity",
        }))]
        mock_anthropic_class.return_value.messages.create.return_value = mock_message

        with self.settings(ENABLE_AI_MATCHING=True, ANTHROPIC_API_KEY="sk-test"):
            run_reconciliation()

        txn.refresh_from_db()
        self.assertEqual(txn.reconciliation_status, "auto_matched")
        match = Match.objects.get(transaction=txn)
        self.assertIn("AI:", match.note)
