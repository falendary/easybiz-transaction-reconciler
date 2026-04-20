"""Business logic for manual reconciliation actions.

All mutating functions set locked_by_user=True and record performed_by / performed_at.
After every status change the affected invoice's status is recomputed and the parent
transaction's reconciliation_status is re-derived from its current match set.
"""

from decimal import Decimal
from typing import Optional

from django.db.models import Sum
from django.utils import timezone

from reconciler.models import Invoice, Match, Responsible, Transaction


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_txn_status(txn: Transaction) -> str:
    """Derive Transaction.reconciliation_status from its current Match set.

    Parameters:
        txn: Transaction whose matches will be inspected.

    Returns:
        One of the Transaction.reconciliation_status choice values.
    """
    active = txn.matches.exclude(status="rejected")
    if not active.exists():
        return "needs_review"
    if active.filter(status="duplicate").exists():
        return "duplicate"
    if active.filter(status="unrelated").exists():
        return "unrelated"
    review = active.filter(status="needs_review")
    if review.exists():
        return "needs_review"
    return "auto_matched"


def _lock(match: Match, performed_by: Optional[Responsible]) -> None:
    match.locked_by_user = True
    match.performed_by = performed_by
    match.performed_at = timezone.now()


def _save_and_propagate(match: Match) -> None:
    match.save()
    if match.invoice:
        match.invoice.recompute_status()
    txn_status = _derive_txn_status(match.transaction)
    match.transaction.reconciliation_status = txn_status
    match.transaction.save(update_fields=["reconciliation_status"])


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def confirm_match(
    match: Match,
    performed_by: Optional[Responsible] = None,
) -> Match:
    """Confirm a match, locking it from further engine processing.

    Parameters:
        match: The Match to confirm. Must not already be rejected or unrelated.
        performed_by: Optional Responsible who performed the action.

    Returns:
        The updated Match instance.

    Raises:
        ValueError: if the match is already rejected or unrelated.
    """
    if match.status in ("rejected", "unrelated"):
        raise ValueError(f"Cannot confirm a match with status '{match.status}'.")
    match.status = "confirmed"
    _lock(match, performed_by)
    _save_and_propagate(match)
    return match


def reject_match(
    match: Match,
    performed_by: Optional[Responsible] = None,
    note: str = "",
) -> Match:
    """Reject a match and recompute dependent statuses.

    Parameters:
        match: The Match to reject.
        performed_by: Optional Responsible who performed the action.
        note: Optional reason for rejection.

    Returns:
        The updated Match instance.

    Raises:
        ValueError: if the match is already confirmed or manually matched and locked.
    """
    if match.locked_by_user and match.status in ("confirmed", "manually_matched"):
        raise ValueError("Cannot reject a locked confirmed match. Unlock it first.")
    match.status = "rejected"
    if note:
        match.note = note
    _lock(match, performed_by)
    _save_and_propagate(match)
    return match


def mark_match_unrelated(
    match: Match,
    performed_by: Optional[Responsible] = None,
) -> Match:
    """Mark a match (and its parent transaction) as unrelated to any invoice.

    Parameters:
        match: The Match to mark as unrelated.
        performed_by: Optional Responsible who performed the action.

    Returns:
        The updated Match instance.
    """
    match.status = "unrelated"
    match.invoice = None
    _lock(match, performed_by)
    _save_and_propagate(match)
    return match


def unlock_match(match: Match) -> Match:
    """Remove the user lock so the reconciliation engine can reprocess this match.

    Parameters:
        match: The Match to unlock.

    Returns:
        The updated Match instance.
    """
    match.locked_by_user = False
    match.performed_by = None
    match.performed_at = None
    match.save(update_fields=["locked_by_user", "performed_by", "performed_at"])
    return match


def create_manual_match(
    transaction: Transaction,
    invoice: Invoice,
    allocated_amount: Decimal,
    note: str = "",
    performed_by: Optional[Responsible] = None,
) -> Match:
    """Create a manually confirmed Match record.

    Parameters:
        transaction: The Transaction to match.
        invoice: The Invoice to allocate against.
        allocated_amount: Amount to allocate (must not exceed unallocated balance).
        note: Optional free-text note.
        performed_by: Optional Responsible who performed the action.

    Returns:
        The newly created Match instance.

    Raises:
        ValueError: if allocated_amount would over-allocate the transaction.
    """
    existing_total = (
        transaction.matches
        .exclude(status__in=["rejected", "unrelated"])
        .aggregate(total=Sum("allocated_amount"))["total"]
        or Decimal("0")
    )
    if existing_total + allocated_amount > transaction.amount:
        raise ValueError(
            f"Total allocated ({existing_total + allocated_amount}) would exceed "
            f"transaction amount ({transaction.amount})."
        )

    match = Match.objects.create(
        transaction=transaction,
        invoice=invoice,
        allocated_amount=allocated_amount,
        confidence_score=Decimal("1.0"),
        match_type="exact",
        status="manually_matched",
        locked_by_user=True,
        performed_by=performed_by,
        performed_at=timezone.now(),
        note=note or None,
    )
    invoice.recompute_status()
    txn_status = _derive_txn_status(transaction)
    transaction.reconciliation_status = txn_status
    transaction.save(update_fields=["reconciliation_status"])
    return match


def force_close_invoice(
    invoice: Invoice,
    note: str,
    performed_by: Optional[Responsible] = None,
) -> Invoice:
    """Force-close an invoice, bypassing normal status recomputation.

    Parameters:
        invoice: The Invoice to close.
        note: Mandatory justification note.
        performed_by: Optional Responsible who performed the action.

    Returns:
        The updated Invoice instance.

    Raises:
        ValueError: if note is blank.
    """
    if not note or not note.strip():
        raise ValueError("A note is required when force-closing an invoice.")
    invoice.status = "force_closed"
    invoice.force_close_note = note.strip()
    invoice.force_closed_by = performed_by
    invoice.force_closed_at = timezone.now()
    invoice.save(update_fields=["status", "force_close_note", "force_closed_by", "force_closed_at"])
    return invoice
