from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum


class Currency(models.Model):
    """ISO 4217 currency reference table. Seeded via fixture on first migration."""

    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=5)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "currencies"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class Source(models.Model):
    """Origin system that produced the data. Seeded via fixture on first migration."""

    SOURCE_TYPE_CHOICES = [
        ("bank", "Bank"),
        ("payment_processor", "Payment Processor"),
        ("crm", "CRM"),
        ("erp", "ERP"),
        ("manual", "Manual"),
    ]

    name = models.CharField(max_length=128, unique=True)
    source_type = models.CharField(max_length=32, choices=SOURCE_TYPE_CHOICES)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Responsible(models.Model):
    """Profile extension for Django's built-in User. Tracks who performed manual reconciliation actions."""

    ROLE_CHOICES = [
        ("reviewer", "Reviewer"),
        ("admin", "Admin"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="responsible")
    display_name = models.CharField(max_length=128)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default="reviewer")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.display_name


class IngestionEvent(models.Model):
    """Records every file upload. Stores raw content for reprocessing and audit."""

    FILE_TYPE_CHOICES = [
        ("invoices", "Invoices"),
        ("transactions", "Transactions"),
        ("payout", "Payout"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    file_type = models.CharField(max_length=16, choices=FILE_TYPE_CHOICES)
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    raw_content = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(null=True, blank=True)
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="ingestion_events")

    def __str__(self) -> str:
        return f"{self.file_type} — {self.filename} ({self.status})"


class Customer(models.Model):
    """A billing client of the SME. Parsed from invoices.json on ingestion."""

    customer_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=256)
    vat_number = models.CharField(max_length=32, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.customer_id} — {self.name}"


class Account(models.Model):
    """One side of the double-entry ledger per customer."""

    ACCOUNT_TYPE_CHOICES = [
        ("receivable", "Accounts Receivable"),
        ("bank", "Bank Account"),
        ("stripe_clearing", "Stripe Clearing"),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="accounts")
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    name = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("customer", "account_type", "currency")]

    def __str__(self) -> str:
        return self.name


class Counterparty(models.Model):
    """Normalized bank counterparty names. Built during transaction ingestion."""

    raw_name = models.CharField(max_length=256, unique=True)
    normalized_name = models.CharField(max_length=256)
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="counterparties"
    )
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "counterparties"

    def __str__(self) -> str:
        return self.normalized_name


class FXRate(models.Model):
    """Exchange rate for a specific date. Seeded with fixed demo rates."""

    SOURCE_CHOICES = [
        ("fixed_demo", "Fixed Demo"),
        ("ECB", "ECB"),
    ]

    base_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="fx_base")
    quote_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="fx_quote")
    rate = models.DecimalField(max_digits=12, decimal_places=6)
    date = models.DateField()
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="fixed_demo")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("base_currency", "quote_currency", "date")]

    def __str__(self) -> str:
        return f"{self.base_currency}/{self.quote_currency} {self.date} = {self.rate}"


class Invoice(models.Model):
    """An invoice or credit note issued by the SME to a customer.

    status is always derived — recomputed from confirmed Match records via recompute_status().
    Never set Invoice.status directly.
    """

    TYPE_CHOICES = [
        ("invoice", "Invoice"),
        ("credit_note", "Credit Note"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("partially_paid", "Partially Paid"),
        ("paid", "Paid"),
        ("force_closed", "Force Closed"),
    ]

    invoice_id = models.CharField(max_length=32, unique=True)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default="invoice")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices")
    issue_date = models.DateField()
    due_date = models.DateField()
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    force_close_note = models.TextField(null=True, blank=True)
    force_closed_by = models.ForeignKey(
        Responsible, null=True, blank=True, on_delete=models.SET_NULL, related_name="force_closed_invoices"
    )
    force_closed_at = models.DateTimeField(null=True, blank=True)
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    ingestion_event = models.ForeignKey(IngestionEvent, on_delete=models.PROTECT, related_name="invoices")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.invoice_id} ({self.status})"

    def recompute_status(self) -> None:
        """Recompute and save invoice status from active Match records.

        Does nothing if the invoice is force_closed — that state is only
        cleared by an explicit unlock action.
        """
        if self.status == "force_closed":
            return
        allocated = (
            self.matches.filter(status__in=["auto_matched", "confirmed", "manually_matched"])
            .aggregate(total=Sum("allocated_amount"))["total"]
            or 0
        )
        if allocated == 0:
            self.status = "open"
        elif allocated >= self.total:
            self.status = "paid"
        else:
            self.status = "partially_paid"
        self.save(update_fields=["status"])


class InvoiceLineItem(models.Model):
    """Individual line items belonging to an invoice."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")
    line_id = models.CharField(max_length=64)
    description = models.CharField(max_length=512)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self) -> str:
        return f"{self.invoice.invoice_id} — {self.description}"


class Transaction(models.Model):
    """A single bank account movement. Imported from transactions.json.

    reconciliation_status is the operational field for the review queue.
    locked_by_user is the protection gate — reconciliation engine never touches locked records.
    """

    RECONCILIATION_STATUS_CHOICES = [
        ("unprocessed", "Unprocessed"),
        ("auto_matched", "Auto Matched"),
        ("needs_review", "Needs Review"),
        ("reconciled", "Reconciled"),
        ("unrelated", "Unrelated"),
        ("duplicate", "Duplicate"),
    ]

    transaction_id = models.CharField(max_length=32, unique=True)
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT)
    counterparty = models.ForeignKey(
        Counterparty, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions"
    )
    raw_counterparty = models.CharField(max_length=256)
    structured_reference = models.CharField(max_length=256, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    is_duplicate = models.BooleanField(default=False)
    reconciliation_status = models.CharField(
        max_length=16, choices=RECONCILIATION_STATUS_CHOICES, default="unprocessed"
    )
    locked_by_user = models.BooleanField(default=False)
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions"
    )
    ingestion_event = models.ForeignKey(IngestionEvent, on_delete=models.PROTECT, related_name="transactions")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.transaction_id} {self.date} {self.amount}"


class PayoutLine(models.Model):
    """Individual charge lines extracted from a Stripe payout CSV.

    Each PayoutLine belongs to the single Stripe Transaction (TXN-0043).
    Refund and chargeback lines have no invoice reference and go to needs_review.
    """

    TYPE_CHOICES = [
        ("charge", "Charge"),
        ("refund", "Refund"),
        ("chargeback", "Chargeback"),
        ("payout", "Payout"),
    ]

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="payout_lines")
    charge_id = models.CharField(max_length=64, unique=True)
    raw_invoice_id = models.CharField(max_length=32, null=True, blank=True)
    customer_name = models.CharField(max_length=256)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    fee = models.DecimalField(max_digits=12, decimal_places=2)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    ingestion_event = models.ForeignKey(IngestionEvent, on_delete=models.PROTECT, related_name="payout_lines")

    def __str__(self) -> str:
        return f"{self.charge_id} ({self.type}) {self.net_amount}"


class Match(models.Model):
    """The reconciliation fact — one allocation line between one Transaction and one Invoice.

    Multiple Match records form complex relationships (partial payments, consolidated splits).
    locked_by_user=True means the reconciliation engine will never modify this record.
    Integrity rule: SUM(allocated_amount) for active matches on a transaction == transaction.amount.
    """

    MATCH_TYPE_CHOICES = [
        ("exact", "Exact"),
        ("partial", "Partial"),
        ("consolidated", "Consolidated"),
        ("fx", "FX"),
        ("credit_note", "Credit Note"),
        ("payout", "Payout"),
        ("noise", "Noise"),
        ("duplicate", "Duplicate"),
        ("prepayment", "Prepayment"),
    ]
    STATUS_CHOICES = [
        ("auto_matched", "Auto Matched"),
        ("needs_review", "Needs Review"),
        ("confirmed", "Confirmed"),
        ("manually_matched", "Manually Matched"),
        ("rejected", "Rejected"),
        ("unrelated", "Unrelated"),
    ]

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="matches")
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="matches"
    )
    payout_line = models.ForeignKey(
        PayoutLine, null=True, blank=True, on_delete=models.SET_NULL, related_name="matches"
    )
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2)
    confidence_score = models.DecimalField(max_digits=4, decimal_places=2)
    match_type = models.CharField(max_length=16, choices=MATCH_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    locked_by_user = models.BooleanField(default=False)
    performed_by = models.ForeignKey(
        Responsible, null=True, blank=True, on_delete=models.SET_NULL, related_name="performed_matches"
    )
    performed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "matches"

    def __str__(self) -> str:
        return f"Match({self.transaction_id} → {self.invoice_id}) [{self.status}]"


class AccountEntry(models.Model):
    """Double-entry bookkeeping ledger line.

    Created automatically via Django signal on Match save — never created manually.
    Every Match produces exactly two AccountEntry rows (receivable + bank).
    """

    ENTRY_TYPE_CHOICES = [
        ("debit", "Debit"),
        ("credit", "Credit"),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="entries")
    match = models.ForeignKey(
        Match, null=True, blank=True, on_delete=models.SET_NULL, related_name="account_entries"
    )
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="account_entries"
    )
    transaction = models.ForeignKey(
        Transaction, null=True, blank=True, on_delete=models.SET_NULL, related_name="account_entries"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    entry_type = models.CharField(max_length=8, choices=ENTRY_TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "account entries"

    def __str__(self) -> str:
        return f"{self.entry_type} {self.amount} [{self.account}]"


class ReconciliationRun(models.Model):
    """Records each reconciliation run for audit and debugging."""

    STATUS_CHOICES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running")
    total_processed = models.PositiveIntegerField(default=0)
    auto_matched_count = models.PositiveIntegerField(default=0)
    needs_review_count = models.PositiveIntegerField(default=0)
    skipped_locked_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Run #{self.pk} {self.status} ({self.started_at:%Y-%m-%d %H:%M})"
