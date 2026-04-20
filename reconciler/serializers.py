from django.db.models import Sum
from rest_framework import serializers

from reconciler.models import (
    Account,
    AccountEntry,
    Counterparty,
    Currency,
    Customer,
    FXRate,
    IngestionEvent,
    Invoice,
    InvoiceLineItem,
    Match,
    PayoutLine,
    ReconciliationRun,
    Responsible,
    Source,
    Transaction,
)


# ---------------------------------------------------------------------------
# Inline serializers — used for nesting, never exposed as top-level endpoints
# ---------------------------------------------------------------------------

class CustomerInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "customer_id", "name"]


class InvoiceInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "invoice_id", "total", "status"]


class TransactionInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ["id", "transaction_id", "amount", "date"]


class AccountInlineSerializer(serializers.ModelSerializer):
    currency = serializers.StringRelatedField()

    class Meta:
        model = Account
        fields = ["id", "account_type", "currency"]


class MatchInlineSerializer(serializers.ModelSerializer):
    """Lightweight match used inside Invoice/Transaction detail responses."""

    invoice_id = serializers.CharField(source="invoice.invoice_id", read_only=True, default=None)
    transaction_id = serializers.CharField(source="transaction.transaction_id", read_only=True)

    class Meta:
        model = Match
        fields = [
            "id", "transaction_id", "invoice_id",
            "allocated_amount", "confidence_score", "match_type", "status",
        ]


class PayoutLineInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutLine
        fields = ["charge_id", "raw_invoice_id", "customer_name", "gross_amount", "fee", "net_amount", "type"]


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ["id", "code", "name", "symbol", "decimal_places", "is_active"]


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ["id", "name", "source_type", "description", "is_active"]


class ResponsibleSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Responsible
        fields = ["id", "display_name", "role", "username"]


class FXRateSerializer(serializers.ModelSerializer):
    base_currency = serializers.SlugRelatedField(slug_field="code", queryset=Currency.objects.all())
    quote_currency = serializers.SlugRelatedField(slug_field="code", queryset=Currency.objects.all())

    class Meta:
        model = FXRate
        fields = ["id", "base_currency", "quote_currency", "rate", "date", "source"]


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

class IngestionEventSerializer(serializers.ModelSerializer):
    source = serializers.StringRelatedField()

    class Meta:
        model = IngestionEvent
        fields = ["id", "file_type", "filename", "source", "status", "error_message", "uploaded_at"]


class IngestionEventDetailSerializer(IngestionEventSerializer):
    class Meta(IngestionEventSerializer.Meta):
        fields = IngestionEventSerializer.Meta.fields + ["raw_content"]


# ---------------------------------------------------------------------------
# Customers & Counterparties
# ---------------------------------------------------------------------------

class CustomerListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "customer_id", "name", "vat_number", "address", "created_at"]


class CustomerDetailSerializer(CustomerListSerializer):
    accounts = AccountInlineSerializer(many=True, read_only=True)
    reconciliation_balance = serializers.SerializerMethodField()

    class Meta(CustomerListSerializer.Meta):
        fields = CustomerListSerializer.Meta.fields + ["accounts", "reconciliation_balance"]

    def get_reconciliation_balance(self, customer: Customer) -> str:
        receivable = (
            AccountEntry.objects.filter(
                account__customer=customer, account__account_type="receivable"
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        bank = (
            AccountEntry.objects.filter(
                account__customer=customer, account__account_type="bank"
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        return str((receivable + bank).quantize(receivable.__class__("0.01")) if hasattr(receivable, "quantize") else round(float(receivable + bank), 2))


class CounterpartySerializer(serializers.ModelSerializer):
    customer = CustomerInlineSerializer(read_only=True)
    customer_id = serializers.PrimaryKeyRelatedField(
        source="customer", queryset=Customer.objects.all(), write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Counterparty
        fields = ["id", "raw_name", "normalized_name", "customer", "customer_id", "description", "created_at"]


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = ["line_id", "description", "quantity", "unit_price", "tax_rate", "amount"]


class InvoiceListSerializer(serializers.ModelSerializer):
    customer = CustomerInlineSerializer(read_only=True)
    currency = serializers.StringRelatedField()

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_id", "type", "customer", "issue_date", "due_date",
            "currency", "subtotal", "tax_total", "total", "status", "force_close_note",
        ]


class InvoiceDetailSerializer(InvoiceListSerializer):
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    matches = MatchInlineSerializer(many=True, read_only=True)

    class Meta(InvoiceListSerializer.Meta):
        fields = InvoiceListSerializer.Meta.fields + ["line_items", "matches", "created_at"]


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class TransactionListSerializer(serializers.ModelSerializer):
    currency = serializers.StringRelatedField()

    class Meta:
        model = Transaction
        fields = [
            "id", "transaction_id", "date", "amount", "currency",
            "raw_counterparty", "structured_reference", "description",
            "is_duplicate", "reconciliation_status", "locked_by_user",
        ]


class TransactionDetailSerializer(TransactionListSerializer):
    payout_lines = PayoutLineInlineSerializer(many=True, read_only=True)
    matches = MatchInlineSerializer(many=True, read_only=True)

    class Meta(TransactionListSerializer.Meta):
        fields = TransactionListSerializer.Meta.fields + ["payout_lines", "matches", "created_at"]


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------

class MatchSerializer(serializers.ModelSerializer):
    transaction = TransactionInlineSerializer(read_only=True)
    invoice = InvoiceInlineSerializer(read_only=True, allow_null=True)
    performed_by = serializers.StringRelatedField()

    class Meta:
        model = Match
        fields = [
            "id", "transaction", "invoice",
            "allocated_amount", "confidence_score", "match_type", "status",
            "locked_by_user", "performed_by", "performed_at", "note",
            "created_at", "updated_at",
        ]


# ---------------------------------------------------------------------------
# Account entries
# ---------------------------------------------------------------------------

class AccountEntrySerializer(serializers.ModelSerializer):
    account = serializers.SerializerMethodField()
    match = serializers.PrimaryKeyRelatedField(read_only=True)
    invoice = InvoiceInlineSerializer(read_only=True, allow_null=True)
    transaction = TransactionInlineSerializer(read_only=True, allow_null=True)

    class Meta:
        model = AccountEntry
        fields = ["id", "account", "entry_type", "amount", "match", "invoice", "transaction", "created_at"]

    def get_account(self, entry: AccountEntry) -> dict:
        return {
            "id": entry.account_id,
            "account_type": entry.account.account_type,
            "customer": entry.account.customer.name,
        }


# ---------------------------------------------------------------------------
# Reconciliation runs
# ---------------------------------------------------------------------------

class ReconciliationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReconciliationRun
        fields = [
            "id", "status", "started_at", "finished_at",
            "total_processed", "auto_matched_count", "needs_review_count",
            "skipped_locked_count", "error_message",
        ]
