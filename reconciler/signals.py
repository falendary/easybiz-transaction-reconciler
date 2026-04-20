"""Django signals for automatic AccountEntry creation/deletion.

post_save on Match  → create debit (receivable) + credit (bank) entries
post_delete on Match → delete the corresponding AccountEntry records
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from reconciler.models import AccountEntry, Match


@receiver(post_save, sender=Match)
def create_account_entries(sender, instance: Match, created: bool, **kwargs) -> None:
    """Create double-entry AccountEntry records when a Match is saved.

    Only fires when the Match links a transaction to an invoice (both present)
    and the match status indicates value flow (auto_matched, confirmed, manually_matched).
    """
    if not created:
        return
    if not instance.invoice or not instance.transaction:
        return
    if instance.status not in ("auto_matched", "confirmed", "manually_matched"):
        return

    invoice = instance.invoice
    customer = invoice.customer
    accounts = {a.account_type: a for a in customer.accounts.all()}

    receivable = accounts.get("receivable")
    bank = accounts.get("bank")
    if not receivable or not bank:
        return

    amount = instance.allocated_amount

    AccountEntry.objects.create(
        account=receivable,
        match=instance,
        invoice=invoice,
        transaction=instance.transaction,
        entry_type="credit",
        amount=amount,
        description=f"Match {instance.id}: receivable cleared",
    )
    AccountEntry.objects.create(
        account=bank,
        match=instance,
        invoice=invoice,
        transaction=instance.transaction,
        entry_type="debit",
        amount=amount,
        description=f"Match {instance.id}: bank receipt",
    )


@receiver(post_delete, sender=Match)
def delete_account_entries(sender, instance: Match, **kwargs) -> None:
    """Remove AccountEntry records when their parent Match is deleted."""
    AccountEntry.objects.filter(match=instance).delete()
