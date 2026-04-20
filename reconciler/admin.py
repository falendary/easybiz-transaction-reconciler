import io

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse

from reconciler.ingestion_service import ingest_invoices, ingest_payout, ingest_transactions
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
from reconciler.reconciliation_service import run_reconciliation

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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
    """Ingestion event log. Changelist has upload buttons for all three file types."""

    list_display = ["file_type", "filename", "source", "status", "uploaded_at"]
    list_filter = ["file_type", "status", "source"]
    readonly_fields = ["raw_content", "uploaded_at"]
    change_list_template = "admin/reconciler/ingestionevent/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "upload/invoices/",
                self.admin_site.admin_view(self._upload_invoices),
                name="reconciler-upload-invoices",
            ),
            path(
                "upload/transactions/",
                self.admin_site.admin_view(self._upload_transactions),
                name="reconciler-upload-transactions",
            ),
            path(
                "upload/payout/",
                self.admin_site.admin_view(self._upload_payout),
                name="reconciler-upload-payout",
            ),
        ]
        return custom + urls

    # ------------------------------------------------------------------
    # Upload view helpers
    # ------------------------------------------------------------------

    def _handle_upload(self, request, service_fn, allowed_ext: str, context: dict):
        """Shared POST handler for all three upload views."""
        result = None
        if request.method == "POST":
            f = request.FILES.get("file")
            if not f:
                result = {"status": "error", "message": "No file provided.", "detail": ""}
            elif f.size > MAX_UPLOAD_BYTES:
                result = {"status": "error", "message": f"File too large ({f.size} bytes). Max 20 MB.", "detail": ""}
            elif not f.name.lower().endswith(f".{allowed_ext}"):
                result = {"status": "error", "message": f"Expected a .{allowed_ext} file.", "detail": ""}
            else:
                try:
                    raw = f.read().decode("utf-8")
                    summary = service_fn(raw, f.name)
                    detail = "\n".join(f"{k}: {v}" for k, v in summary.items())
                    result = {"status": "success", "message": "File ingested successfully.", "detail": detail}
                    messages.success(request, f"Uploaded {f.name} — {detail.replace(chr(10), ', ')}")
                except Exception as exc:
                    result = {"status": "error", "message": str(exc), "detail": ""}
        return render(request, "admin/reconciler/upload_form.html", {**context, "result": result})

    def _upload_invoices(self, request):
        return self._handle_upload(
            request,
            ingest_invoices,
            "json",
            {
                "title": "Upload Invoices JSON",
                "file_label": "invoices.json",
                "accept": ".json",
                "help_text": "JSON array of invoice records. Re-uploading is safe (upsert on invoice_id).",
            },
        )

    def _upload_transactions(self, request):
        return self._handle_upload(
            request,
            ingest_transactions,
            "json",
            {
                "title": "Upload Transactions JSON",
                "file_label": "transactions.json",
                "accept": ".json",
                "help_text": "JSON array of bank transactions. [RE-IMPORTED] prefix sets is_duplicate=true.",
            },
        )

    def _upload_payout(self, request):
        return self._handle_upload(
            request,
            ingest_payout,
            "csv",
            {
                "title": "Upload Stripe Payout CSV",
                "file_label": "payout_report.csv",
                "accept": ".csv",
                "help_text": "Stripe payout CSV. Transactions must be uploaded first.",
            },
        )


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
    """Reconciliation run history. Changelist has a 'Run Reconciliation' button."""

    list_display = [
        "id", "status", "started_at", "finished_at",
        "total_processed", "auto_matched_count", "needs_review_count", "skipped_locked_count",
    ]
    list_filter = ["status"]
    readonly_fields = ["started_at"]
    change_list_template = "admin/reconciler/reconciliationrun/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "run/",
                self.admin_site.admin_view(self._run_reconciliation),
                name="reconciler-run-reconciliation",
            ),
        ]
        return custom + urls

    def _run_reconciliation(self, request):
        """Trigger a full reconciliation run and redirect back to the changelist."""
        if request.method != "POST":
            return HttpResponseRedirect(
                reverse("admin:reconciler_reconciliationrun_changelist")
            )
        try:
            run = run_reconciliation()
            messages.success(
                request,
                f"Reconciliation complete — {run.total_processed} processed, "
                f"{run.auto_matched_count} auto-matched, {run.needs_review_count} need review.",
            )
        except Exception as exc:
            messages.error(request, f"Reconciliation failed: {exc}")
        return HttpResponseRedirect(
            reverse("admin:reconciler_reconciliationrun_changelist")
        )
