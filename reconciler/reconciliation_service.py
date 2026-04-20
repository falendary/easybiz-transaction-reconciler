"""Reconciliation engine — matches transactions to invoices using priority rules.

Rules fire in order; first match wins per transaction.
Locked transactions (locked_by_user=True) are never touched.
Running twice on the same data produces identical results (idempotent).
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from reconciler.models import (
    Invoice,
    Match,
    PayoutLine,
    ReconciliationRun,
    Transaction,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = Decimal("0.85")
FX_TOLERANCE = Decimal("0.02")  # 2 %

NOISE_COUNTERPARTY_KEYWORDS = [
    "payroll", "salary", "salaire",
    "immo lux", "landlord", "loyer",
    "enovos", "electricit",
    "slack", "amazon",
    "securex", "bcee", "bank fee", "frais bancaire",
]

# Matches bare INV-YYYY-NNNN / CN-YYYY-NNNN and prefixed forms like SHOWCASE-03-INV-YYYY-NNNN.
INVOICE_ID_RE = re.compile(r"\b((?:[A-Z0-9]+-)*(?:INV|CN)[-\s]?\d{4}[-\s]?\d{4})\b", re.IGNORECASE)
PAYOUT_ID_RE = re.compile(r"^po_", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Internal result type
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    """One potential Match record to be created for a transaction."""
    invoice: Optional[Invoice]
    allocated_amount: Decimal
    confidence: Decimal
    match_type: str
    txn_status: str           # final Transaction.reconciliation_status contribution
    payout_line: Optional[PayoutLine] = None
    note: str = ""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_noise(txn: Transaction) -> bool:
    lower = txn.raw_counterparty.lower()
    return any(kw in lower for kw in NOISE_COUNTERPARTY_KEYWORDS)


def _fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _normalize_id(raw: str) -> str:
    """Canonicalise an invoice ID to INV-YYYY-NNNN / CN-YYYY-NNNN."""
    raw = re.sub(r"\s+", "-", raw.strip().upper())
    raw = re.sub(r"-+", "-", raw)
    # Handle no-separator form: INV20260001 → INV-2026-0001
    raw = re.sub(r"^(INV|CN)(\d{4})(\d{4})$", r"\1-\2-\3", raw)
    return raw


def _extract_ids(text: str) -> list[str]:
    """Extract all canonical invoice/credit-note IDs from free text."""
    if not text:
        return []
    return [_normalize_id(m) for m in INVOICE_ID_RE.findall(text)]


def _within_tolerance(txn_amount: Decimal, invoice_total: Decimal) -> bool:
    if invoice_total == 0:
        return False
    return abs(txn_amount - invoice_total) / abs(invoice_total) <= FX_TOLERANCE


def _match_status(confidence: Decimal) -> str:
    return "auto_matched" if confidence >= CONFIDENCE_THRESHOLD else "needs_review"


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------

def _rule1_noise(txn: Transaction) -> Optional[list[_Candidate]]:
    """Negative amount or known-noise counterparty → unrelated."""
    if txn.amount < 0 or _is_noise(txn):
        return [_Candidate(
            invoice=None,
            allocated_amount=txn.amount,
            confidence=Decimal("1.0"),
            match_type="noise",
            txn_status="unrelated",
        )]
    return None


def _rule2_duplicate(txn: Transaction) -> Optional[list[_Candidate]]:
    """[RE-IMPORTED] flag → duplicate."""
    if txn.is_duplicate:
        return [_Candidate(
            invoice=None,
            allocated_amount=txn.amount,
            confidence=Decimal("1.0"),
            match_type="duplicate",
            txn_status="duplicate",
        )]
    return None


def _rule3_payout(txn: Transaction) -> Optional[list[_Candidate]]:
    """Stripe payout reference → decompose via PayoutLines."""
    if not PAYOUT_ID_RE.match(txn.structured_reference or ""):
        return None
    lines = list(PayoutLine.objects.filter(transaction=txn))
    if not lines:
        return None

    candidates: list[_Candidate] = []
    for line in lines:
        if line.type == "payout":
            continue  # summary row, skip

        if line.type == "charge" and line.raw_invoice_id:
            try:
                invoice = Invoice.objects.get(invoice_id=line.raw_invoice_id)
                conf = Decimal("0.95")
            except Invoice.DoesNotExist:
                invoice = None
                conf = Decimal("0.0")
        else:
            # refund / chargeback — no invoice link, send to review
            invoice = None
            conf = Decimal("0.0")

        candidates.append(_Candidate(
            invoice=invoice,
            allocated_amount=line.net_amount,
            confidence=conf,
            match_type="payout",
            txn_status=_match_status(conf) if invoice else "needs_review",
            payout_line=line,
            note=f"Stripe {line.type}; fee={line.fee}" if line.type == "charge" else f"Stripe {line.type} — manual review required",
        ))

    return candidates or None


def _rule4_exact(txn: Transaction) -> Optional[list[_Candidate]]:
    """Structured reference + exact amount match."""
    ref = txn.structured_reference
    if not ref:
        return None
    try:
        invoice = Invoice.objects.get(invoice_id=_normalize_id(ref))
    except Invoice.DoesNotExist:
        return None
    if txn.amount == invoice.total:
        return [_Candidate(
            invoice=invoice,
            allocated_amount=txn.amount,
            confidence=Decimal("0.95"),
            match_type="exact",
            txn_status="auto_matched",
        )]
    return None


def _rule5_fx_tolerance(txn: Transaction) -> Optional[list[_Candidate]]:
    """Structured reference + amount within 2 % (FX drift / overpayment rounding)."""
    ref = txn.structured_reference
    if not ref:
        return None
    try:
        invoice = Invoice.objects.get(invoice_id=_normalize_id(ref))
    except Invoice.DoesNotExist:
        return None
    if _within_tolerance(txn.amount, invoice.total):
        return [_Candidate(
            invoice=invoice,
            allocated_amount=txn.amount,
            confidence=Decimal("0.85"),
            match_type="fx",
            txn_status="auto_matched",
        )]
    return None


def _rule6_consolidated(txn: Transaction) -> Optional[list[_Candidate]]:
    """Multiple invoice IDs in description → proportional split.

    If the transaction amount exactly equals the sum of all found invoices,
    confidence is raised to 0.95 (auto_matched). Otherwise 0.75 (needs_review).
    """
    text = (txn.description or "") + " " + (txn.structured_reference or "")
    ids = _extract_ids(text)
    if len(ids) < 2:
        return None
    invoices = list(Invoice.objects.filter(invoice_id__in=ids))
    if len(invoices) < 2:
        return None

    total_invoiced = sum(i.total for i in invoices) or Decimal("1")
    if txn.amount == total_invoiced:
        conf = Decimal("0.95")
        txn_status = "auto_matched"
    else:
        conf = Decimal("0.75")
        txn_status = "needs_review"

    return [
        _Candidate(
            invoice=inv,
            allocated_amount=(txn.amount * inv.total / total_invoiced).quantize(Decimal("0.01")),
            confidence=conf,
            match_type="consolidated",
            txn_status=txn_status,
        )
        for inv in invoices
    ]


def _rule7_partial(txn: Transaction) -> Optional[list[_Candidate]]:
    """Structured reference matches an invoice but amount is less than total (partial payment).

    If all transactions sharing the same structured_reference sum exactly to the invoice
    total, the split is intentional — confidence is raised to 0.95 (auto_matched).
    Otherwise confidence is 0.75 (needs_review).
    """
    ref = txn.structured_reference
    if not ref:
        return None
    try:
        invoice = Invoice.objects.get(invoice_id=_normalize_id(ref))
    except Invoice.DoesNotExist:
        return None
    if txn.amount >= invoice.total:
        return None

    all_txns_total = (
        Transaction.objects.filter(structured_reference=ref)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    if all_txns_total == invoice.total:
        conf = Decimal("0.95")
        txn_status = "auto_matched"
        note = ""
    else:
        conf = Decimal("0.75")
        txn_status = "needs_review"
        note = (
            f"Partial payment: this transaction {txn.amount}, "
            f"invoice total {invoice.total}, "
            f"all payments so far {all_txns_total}"
        )

    return [_Candidate(
        invoice=invoice,
        allocated_amount=txn.amount,
        confidence=conf,
        match_type="partial",
        txn_status=txn_status,
        note=note,
    )]


def _rule8_fuzzy(txn: Transaction) -> Optional[list[_Candidate]]:
    """Fuzzy match: extract invoice IDs from description, or match counterparty to customer name."""
    text = (txn.description or "") + " " + (txn.structured_reference or "")
    for raw_id in _extract_ids(text):
        try:
            invoice = Invoice.objects.get(invoice_id=raw_id)
            return [_Candidate(
                invoice=invoice,
                allocated_amount=txn.amount,
                confidence=Decimal("0.70"),
                match_type="exact",
                txn_status="needs_review",
                note=f"Invoice ID extracted from description: {raw_id}",
            )]
        except Invoice.DoesNotExist:
            continue

    if txn.raw_counterparty:
        best_invoice: Optional[Invoice] = None
        best_score = 0.0
        for inv in Invoice.objects.select_related("customer").filter(status__in=["open", "partially_paid"]):
            score = _fuzzy(txn.raw_counterparty, inv.customer.name)
            if score >= 0.6 and score > best_score and _within_tolerance(txn.amount, inv.total):
                best_score = score
                best_invoice = inv
        if best_invoice:
            return [_Candidate(
                invoice=best_invoice,
                allocated_amount=txn.amount,
                confidence=Decimal("0.70"),
                match_type="exact",
                txn_status="needs_review",
                note=f"Fuzzy counterparty match (score={best_score:.2f})",
            )]
    return None


def _rule9_ai(txn: Transaction) -> Optional[list[_Candidate]]:
    """Claude AI fallback — fires only when ENABLE_AI_MATCHING=true."""
    if not getattr(settings, "ENABLE_AI_MATCHING", False):
        return None
    from reconciler.claude_service import ai_match_transaction  # lazy import

    candidates = list(Invoice.objects.select_related("customer").filter(status__in=["open", "partially_paid"]))
    if not candidates:
        return None

    result = ai_match_transaction(txn, candidates)
    if result is None:
        return None

    invoice, confidence, note = result
    conf = Decimal(str(confidence))
    return [_Candidate(
        invoice=invoice,
        allocated_amount=txn.amount,
        confidence=conf,
        match_type="exact",
        txn_status=_match_status(conf),
        note=f"AI: {note}",
    )]


_RULES = [
    _rule1_noise,
    _rule2_duplicate,
    _rule3_payout,
    _rule4_exact,
    _rule5_fx_tolerance,
    _rule6_consolidated,
    _rule7_partial,
    _rule8_fuzzy,
    _rule9_ai,
]


# ---------------------------------------------------------------------------
# Per-transaction processor
# ---------------------------------------------------------------------------

def _process_transaction(txn: Transaction) -> str:
    """Apply rules to one transaction, create Match records, return final txn status.

    Parameters:
        txn: Transaction instance with locked_by_user=False

    Returns:
        The reconciliation_status string assigned to the transaction.
    """
    # Delete previous unlocked matches (idempotency)
    txn.matches.filter(locked_by_user=False).delete()

    candidates: Optional[list[_Candidate]] = None
    for rule in _RULES:
        candidates = rule(txn)
        if candidates is not None:
            break

    if not candidates:
        # Rule 10: no match found
        Match.objects.create(
            transaction=txn,
            invoice=None,
            allocated_amount=txn.amount,
            confidence_score=Decimal("0.0"),
            match_type="exact",
            status="needs_review",
            note="No matching invoice found",
        )
        txn.reconciliation_status = "needs_review"
        txn.save(update_fields=["reconciliation_status"])
        return "needs_review"

    affected_invoices: set[Invoice] = set()
    first_txn_status = candidates[0].txn_status

    for c in candidates:
        # Direct statuses (unrelated/duplicate) bypass confidence threshold
        if first_txn_status in ("unrelated", "duplicate"):
            match_status = "unrelated"
        else:
            match_status = _match_status(c.confidence)

        Match.objects.create(
            transaction=txn,
            invoice=c.invoice,
            payout_line=c.payout_line,
            allocated_amount=c.allocated_amount,
            confidence_score=c.confidence,
            match_type=c.match_type,
            status=match_status,
            note=c.note or None,
        )
        if c.invoice:
            affected_invoices.add(c.invoice)

    # Derive Transaction.reconciliation_status
    if first_txn_status in ("unrelated", "duplicate"):
        txn_status = first_txn_status
    elif all(c.confidence >= CONFIDENCE_THRESHOLD for c in candidates if c.invoice):
        txn_status = "auto_matched"
    else:
        txn_status = "needs_review"

    txn.reconciliation_status = txn_status
    txn.save(update_fields=["reconciliation_status"])

    for invoice in affected_invoices:
        invoice.recompute_status()

    return txn_status


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_reconciliation() -> ReconciliationRun:
    """Run the reconciliation engine over all unlocked transactions.

    Parameters: none

    Returns:
        Completed ReconciliationRun record with summary counts.

    Raises:
        Exception: propagated if an unexpected error occurs; run.status set to 'failed'.
    """
    if ReconciliationRun.objects.filter(status="running").exists():
        raise ValueError("A reconciliation run is already in progress.")

    run = ReconciliationRun.objects.create(status="running")

    transactions = Transaction.objects.filter(locked_by_user=False).order_by("date", "transaction_id")
    skipped_locked = Transaction.objects.filter(locked_by_user=True).count()

    total = auto_matched = needs_review = 0

    try:
        for txn in transactions:
            status = _process_transaction(txn)
            total += 1
            if status == "auto_matched":
                auto_matched += 1
            elif status == "needs_review":
                needs_review += 1
        run.status = "completed"
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        raise
    finally:
        run.finished_at = timezone.now()
        run.total_processed = total
        run.auto_matched_count = auto_matched
        run.needs_review_count = needs_review
        run.skipped_locked_count = skipped_locked
        run.save()

    return run
