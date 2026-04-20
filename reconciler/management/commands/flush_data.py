"""Management command to wipe all ingested and reconciled data.

Preserves: Currency, Source, FXRate, Responsible.
Deletes everything else in dependency order to avoid FK violations.

Usage:
    venv/bin/python manage.py flush_data          # prompts for confirmation
    venv/bin/python manage.py flush_data --yes    # skips prompt (CI / scripts)
"""

from django.core.management.base import BaseCommand

from reconciler.models import (
    Account,
    AccountEntry,
    Counterparty,
    Customer,
    IngestionEvent,
    Invoice,
    Match,
    PayoutLine,
    ReconciliationRun,
    Transaction,
)


class Command(BaseCommand):
    help = "Delete all ingested/reconciled data. Preserves Currency, Source, FXRate, Responsible."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt.",
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            self.stdout.write(
                self.style.WARNING(
                    "This will permanently delete all transactions, invoices, matches, "
                    "payout lines, customers, accounts, counterparties, ingestion events, "
                    "and reconciliation runs.\n"
                    "FX rates, currencies, sources, and responsibles are kept.\n"
                )
            )
            confirm = input("Type 'yes' to continue: ").strip().lower()
            if confirm != "yes":
                self.stdout.write("Aborted.")
                return

        steps = [
            ("Account entries",      AccountEntry.objects.all()),
            ("Matches",              Match.objects.all()),
            ("Payout lines",         PayoutLine.objects.all()),
            ("Invoices",             Invoice.objects.all()),
            ("Transactions",         Transaction.objects.all()),
            ("Accounts",             Account.objects.all()),
            ("Counterparties",       Counterparty.objects.all()),
            ("Customers",            Customer.objects.all()),
            ("Ingestion events",     IngestionEvent.objects.all()),
            ("Reconciliation runs",  ReconciliationRun.objects.all()),
        ]

        for label, qs in steps:
            count, _ = qs.delete()
            self.stdout.write(f"  {label}: {count} deleted")

        self.stdout.write(self.style.SUCCESS("Done. Ready for a fresh upload."))
