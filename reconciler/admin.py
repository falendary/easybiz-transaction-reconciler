from django.contrib import admin

from reconciler.models import (
    Account,
    AccountEntry,
    Currency,
    Counterparty,
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


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "symbol", "decimal_places", "is_active"]
    list_filter = ["is_active"]


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["name", "source_type", "is_active", "created_at"]
    list_filter = ["source_type", "is_active"]


@admin.register(Responsible)
class ResponsibleAdmin(admin.ModelAdmin):
    list_display = ["display_name", "user", "role", "created_at"]
    list_filter = ["role"]


@admin.register(IngestionEvent)
class IngestionEventAdmin(admin.ModelAdmin):
    list_display = ["file_type", "filename", "source", "status", "uploaded_at"]
    list_filter = ["file_type", "status", "source"]
    readonly_fields = ["raw_content", "uploaded_at"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["customer_id", "name", "vat_number", "created_at"]
    search_fields = ["customer_id", "name", "vat_number"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["name", "customer", "account_type", "currency", "created_at"]
    list_filter = ["account_type", "currency"]


@admin.register(Counterparty)
class CounterpartyAdmin(admin.ModelAdmin):
    list_display = ["raw_name", "normalized_name", "customer", "created_at"]
    list_filter = ["customer"]
    search_fields = ["raw_name", "normalized_name"]


@admin.register(FXRate)
class FXRateAdmin(admin.ModelAdmin):
    list_display = ["base_currency", "quote_currency", "rate", "date", "source"]
    list_filter = ["base_currency", "quote_currency", "source"]
    date_hierarchy = "date"


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ["line_id", "description", "quantity", "unit_price", "tax_rate", "amount"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ["invoice_id", "type", "customer", "total", "currency", "status", "issue_date", "due_date"]
    list_filter = ["type", "status", "currency", "customer"]
    search_fields = ["invoice_id", "customer__name"]
    date_hierarchy = "issue_date"
    readonly_fields = ["status", "created_at"]
    inlines = [InvoiceLineItemInline]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        "transaction_id", "date", "amount", "currency",
        "raw_counterparty", "reconciliation_status", "is_duplicate", "locked_by_user",
    ]
    list_filter = ["reconciliation_status", "is_duplicate", "locked_by_user", "currency"]
    search_fields = ["transaction_id", "raw_counterparty", "structured_reference", "description"]
    date_hierarchy = "date"
    readonly_fields = ["created_at"]


@admin.register(PayoutLine)
class PayoutLineAdmin(admin.ModelAdmin):
    list_display = ["charge_id", "transaction", "type", "customer_name", "gross_amount", "fee", "net_amount"]
    list_filter = ["type"]
    search_fields = ["charge_id", "raw_invoice_id", "customer_name"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = [
        "id", "transaction", "invoice", "allocated_amount",
        "confidence_score", "match_type", "status", "locked_by_user", "performed_by",
    ]
    list_filter = ["status", "match_type", "locked_by_user"]
    search_fields = ["transaction__transaction_id", "invoice__invoice_id", "note"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AccountEntry)
class AccountEntryAdmin(admin.ModelAdmin):
    list_display = ["id", "account", "entry_type", "amount", "match", "created_at"]
    list_filter = ["entry_type", "account__account_type"]
    readonly_fields = ["created_at"]


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = [
        "id", "status", "started_at", "finished_at",
        "total_processed", "auto_matched_count", "needs_review_count", "skipped_locked_count",
    ]
    list_filter = ["status"]
    readonly_fields = ["started_at"]