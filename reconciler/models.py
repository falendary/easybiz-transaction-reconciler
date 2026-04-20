from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum


class Currency(models.Model):
    """ISO 4217 currency reference table. Seeded via fixture on first migration."""

    code = models.CharField(max_length=3, unique=True, help_text="ISO 4217 three-letter code, e.g. EUR, USD, GBP.")
    name = models.CharField(max_length=64, help_text="Full currency name, e.g. Euro.")
    symbol = models.CharField(max_length=5, help_text="Display symbol, e.g. €.")
    decimal_places = models.PositiveSmallIntegerField(default=2, help_text="Number of decimal places used for amounts in this currency.")
    is_active = models.BooleanField(default=True, help_text="Inactive currencies are hidden from dropdowns but retained for historical records.")
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

    name = models.CharField(max_length=128, unique=True, help_text="Human-readable source name, e.g. 'ING Bank' or 'Stripe'.")
    source_type = models.CharField(max_length=32, choices=SOURCE_TYPE_CHOICES, help_text="Category of the source system.")
    description = models.TextField(null=True, blank=True, help_text="Optional notes about this source, e.g. account number or API endpoint.")
    is_active = models.BooleanField(default=True, help_text="Inactive sources are excluded from new ingestion but retained for audit.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Responsible(models.Model):
    """Profile extension for Django's built-in User. Tracks who performed manual reconciliation actions."""

    ROLE_CHOICES = [
        ("reviewer", "Reviewer"),
        ("admin", "Admin"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="responsible", help_text="Linked Django user account.")
    display_name = models.CharField(max_length=128, help_text="Full name shown in the audit trail.")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default="reviewer", help_text="Reviewers can confirm/reject matches; admins can force-close invoices and unlock matches.")
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

    file_type = models.CharField(max_length=16, choices=FILE_TYPE_CHOICES, help_text="Type of data contained in the uploaded file.")
    filename = models.CharField(max_length=255, help_text="Original filename as uploaded by the user.")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    raw_content = models.TextField(help_text="Verbatim file content stored for audit and potential reprocessing.")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending", help_text="Outcome of the ingestion attempt.")
    error_message = models.TextField(null=True, blank=True, help_text="Exception message if status=failed; empty otherwise.")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="ingestion_events", help_text="System that produced this file.")

    def __str__(self) -> str:
        return f"{self.file_type} — {self.filename} ({self.status})"


class Customer(models.Model):
    """A billing client of the SME. Parsed from invoices.json on ingestion."""

    customer_id = models.CharField(max_length=32, unique=True, help_text="Business-key from the source CRM, e.g. CUST-001.")
    name = models.CharField(max_length=256, help_text="Legal company name as it appears on invoices.")
    vat_number = models.CharField(max_length=32, null=True, blank=True, help_text="EU VAT registration number, e.g. LU12345678.")
    address = models.TextField(null=True, blank=True, help_text="Registered office address.")
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

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="accounts", help_text="Customer this ledger account belongs to.")
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, help_text="Role of this account in the double-entry pair.")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, help_text="Currency denomination of this account.")
    name = models.CharField(max_length=256, help_text="Display name, e.g. 'Acme S.à r.l. — Receivable EUR'.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("customer", "account_type", "currency")]

    def __str__(self) -> str:
        return self.name


class Counterparty(models.Model):
    """Normalized bank counterparty names. Built during transaction ingestion."""

    raw_name = models.CharField(max_length=256, unique=True, help_text="Counterparty name exactly as it appears in the bank export.")
    normalized_name = models.CharField(max_length=256, help_text="Cleaned version used for fuzzy matching; defaults to raw_name on creation.")
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="counterparties",
        help_text="If this counterparty is known to correspond to a customer, link it here to improve match accuracy.",
    )
    description = models.TextField(null=True, blank=True, help_text="Optional notes, e.g. 'law firm pooled client account'.")
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

    base_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="fx_base", help_text="Currency being converted from.")
    quote_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="fx_quote", help_text="Currency being converted to.")
    rate = models.DecimalField(max_digits=12, decimal_places=6, help_text="Units of quote currency per 1 unit of base currency.")
    date = models.DateField(help_text="Date this rate applies to. Use the transaction date when converting amounts.")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="fixed_demo", help_text="Provider of this rate.")
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

    invoice_id = models.CharField(max_length=32, unique=True, help_text="Business-key from the source CRM, e.g. INV-2026-0001 or CN-2026-0001.")
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, default="invoice", help_text="Invoice reduces receivables; credit note is a negative amount that reduces what the customer owes.")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="invoices", help_text="Customer this invoice was issued to.")
    issue_date = models.DateField(help_text="Date the invoice was issued.")
    due_date = models.DateField(help_text="Payment due date.")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, help_text="Currency the invoice is denominated in.")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, help_text="Sum of line items before tax.")
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, help_text="Total tax amount. Negative for credit notes.")
    total = models.DecimalField(max_digits=12, decimal_places=2, help_text="Amount the customer owes (subtotal + tax). Negative for credit notes.")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open", help_text="Derived from matched allocations — do not set directly. Use recompute_status().")
    force_close_note = models.TextField(null=True, blank=True, help_text="Mandatory reason when an admin force-closes an invoice without full payment.")
    force_closed_by = models.ForeignKey(
        Responsible, null=True, blank=True, on_delete=models.SET_NULL, related_name="force_closed_invoices",
        help_text="Admin who force-closed this invoice.",
    )
    force_closed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when the invoice was force-closed.")
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices",
        help_text="System that produced this invoice.",
    )
    ingestion_event = models.ForeignKey(IngestionEvent, on_delete=models.PROTECT, related_name="invoices", help_text="Upload event that created or last updated this invoice.")
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

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items", help_text="Invoice this line belongs to.")
    line_id = models.CharField(max_length=64, help_text="Line item identifier from the source system.")
    description = models.CharField(max_length=512, help_text="Service or product description as it appears on the invoice.")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, help_text="Number of units.")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Price per unit before tax.")
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4, help_text="Tax rate as a decimal, e.g. 0.17 for 17% Luxembourg VAT.")
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Line total including tax (quantity × unit_price × (1 + tax_rate)).")

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

    transaction_id = models.CharField(max_length=32, unique=True, help_text="Business-key from the bank export, e.g. TXN-0001.")
    date = models.DateField(help_text="Value date of the bank movement (ISO 8601).")
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Signed amount: positive = credit (money received), negative = debit (money sent).")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, help_text="Currency the bank booked this transaction in.")
    counterparty = models.ForeignKey(
        Counterparty, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions",
        help_text="Normalized counterparty record. Null until the counterparty is linked to a customer.",
    )
    raw_counterparty = models.CharField(max_length=256, help_text="Counterparty name exactly as it appeared in the bank export.")
    structured_reference = models.CharField(max_length=256, null=True, blank=True, help_text="Payment reference field from the bank (e.g. invoice ID or Stripe payout ID). Primary key for rule-based matching.")
    description = models.TextField(null=True, blank=True, help_text="Free-text payment description from the bank. Mined by Rules 6, 7, and 8 for invoice IDs.")
    is_duplicate = models.BooleanField(default=False, help_text="Set to True when the description starts with [RE-IMPORTED]. Routed to duplicate status by Rule 2.")
    reconciliation_status = models.CharField(
        max_length=16, choices=RECONCILIATION_STATUS_CHOICES, default="unprocessed",
        help_text="Current state in the reconciliation workflow. Derived by the engine; overridden by manual actions.",
    )
    locked_by_user = models.BooleanField(default=False, help_text="When True, the reconciliation engine skips this transaction entirely. Set automatically on manual confirm/reject.")
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions",
        help_text="Bank or system that produced this transaction.",
    )
    ingestion_event = models.ForeignKey(IngestionEvent, on_delete=models.PROTECT, related_name="transactions", help_text="Upload event that created or last updated this transaction.")
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

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="payout_lines", help_text="Parent bank transaction that received this Stripe payout.")
    charge_id = models.CharField(max_length=64, unique=True, help_text="Stripe charge, refund, or payout ID (ch_..., rf_..., cb_..., po_...).")
    raw_invoice_id = models.CharField(max_length=32, null=True, blank=True, help_text="Invoice ID from the Stripe CSV invoice_id column. Null for refunds and chargebacks.")
    customer_name = models.CharField(max_length=256, help_text="Customer name as reported by Stripe.")
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Amount before Stripe fees. Negative for refunds and chargebacks.")
    fee = models.DecimalField(max_digits=12, decimal_places=2, help_text="Stripe processing fee. Zero for refunds and chargebacks.")
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Amount actually credited to the bank account (gross minus fee). Used as allocated_amount on the Match.")
    type = models.CharField(max_length=16, choices=TYPE_CHOICES, help_text="Stripe line type. Charge lines are auto-matched; refund and chargeback lines go to needs_review.")
    ingestion_event = models.ForeignKey(IngestionEvent, on_delete=models.PROTECT, related_name="payout_lines", help_text="Upload event that created this payout line.")

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

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="matches", help_text="Bank transaction this match belongs to.")
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="matches",
        help_text="Invoice being paid by this match. Null for noise, duplicate, and unresolved needs_review records.",
    )
    payout_line = models.ForeignKey(
        PayoutLine, null=True, blank=True, on_delete=models.SET_NULL, related_name="matches",
        help_text="Stripe PayoutLine this match was created from. Set only for payout-type matches.",
    )
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Portion of the transaction amount allocated to this invoice. For consolidated splits this is a fraction of the total.")
    confidence_score = models.DecimalField(max_digits=4, decimal_places=2, help_text="Engine confidence 0.0–1.0. ≥0.85 → auto_matched; <0.85 → needs_review.")
    match_type = models.CharField(max_length=16, choices=MATCH_TYPE_CHOICES, help_text="Which matching rule and pattern produced this record.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, help_text="Current review state. auto_matched and confirmed are considered reconciled.")
    locked_by_user = models.BooleanField(default=False, help_text="When True, the engine will never overwrite this match. Set on every manual action.")
    performed_by = models.ForeignKey(
        Responsible, null=True, blank=True, on_delete=models.SET_NULL, related_name="performed_matches",
        help_text="User who last manually changed this match status.",
    )
    performed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of the last manual action.")
    note = models.TextField(null=True, blank=True, help_text="Engine reason (e.g. 'Fuzzy counterparty match score=0.82') or reviewer comment.")
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

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="entries", help_text="Ledger account this entry is posted to.")
    match = models.ForeignKey(
        Match, null=True, blank=True, on_delete=models.SET_NULL, related_name="account_entries",
        help_text="Match that triggered this entry. Null if the entry was created by a non-match event.",
    )
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="account_entries",
        help_text="Invoice side of the double-entry pair.",
    )
    transaction = models.ForeignKey(
        Transaction, null=True, blank=True, on_delete=models.SET_NULL, related_name="account_entries",
        help_text="Transaction side of the double-entry pair.",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Absolute amount of this entry. Debit and credit entries always have the same amount.")
    entry_type = models.CharField(max_length=8, choices=ENTRY_TYPE_CHOICES, help_text="Debit increases the receivable; credit records the bank receipt.")
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
    finished_at = models.DateTimeField(null=True, blank=True, help_text="Set when the run completes or fails.")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="running", help_text="Current state of the run.")
    total_processed = models.PositiveIntegerField(default=0, help_text="Number of transactions processed (locked records are excluded).")
    auto_matched_count = models.PositiveIntegerField(default=0, help_text="Transactions that reached auto_matched status in this run.")
    needs_review_count = models.PositiveIntegerField(default=0, help_text="Transactions that ended in needs_review and require human action.")
    skipped_locked_count = models.PositiveIntegerField(default=0, help_text="Transactions skipped because locked_by_user=True.")
    error_message = models.TextField(null=True, blank=True, help_text="Exception traceback if status=failed; empty otherwise.")

    def __str__(self) -> str:
        return f"Run #{self.pk} {self.status} ({self.started_at:%Y-%m-%d %H:%M})"
