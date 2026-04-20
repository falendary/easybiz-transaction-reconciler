import io
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse

from reconciler.ingestion_service import ingest_invoices, ingest_payout, ingest_transactions
from reconciler.manual_service import confirm_match, mark_match_unrelated, reject_match
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


class MatchInline(admin.TabularInline):
    """Matches shown inline on the Transaction detail page."""

    model = Match
    extra = 0
    fields = ["invoice", "allocated_amount", "confidence_score", "match_type", "status", "locked_by_user", "note"]
    readonly_fields = ["confidence_score", "match_type", "locked_by_user"]
    show_change_link = True


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Transaction changelist is the primary review workspace.
    Use the Reconciliation Dashboard button for the two-table review/reconciled view.
    """

    list_display = [
        "transaction_id", "date", "amount", "currency",
        "raw_counterparty", "reconciliation_status", "is_duplicate", "locked_by_user",
    ]
    list_filter = ["reconciliation_status", "is_duplicate", "locked_by_user", "currency"]
    search_fields = ["transaction_id", "raw_counterparty", "structured_reference", "description"]
    date_hierarchy = "date"
    readonly_fields = ["transaction_id", "date", "amount", "currency", "raw_counterparty",
                       "structured_reference", "description", "is_duplicate", "created_at"]
    inlines = [MatchInline]
    actions = ["action_confirm_matches", "action_reject_matches", "action_mark_unrelated"]
    change_list_template = "admin/reconciler/transaction/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "dashboard/",
                self.admin_site.admin_view(self._dashboard_view),
                name="reconciler-dashboard",
            ),
        ]
        return custom + urls

    # ------------------------------------------------------------------
    # Bulk admin actions (changelist checkboxes)
    # ------------------------------------------------------------------

    @admin.action(description="Confirm all needs_review matches for selected transactions")
    def action_confirm_matches(self, request, queryset):
        """Confirm every needs_review Match attached to the selected transactions."""
        confirmed = 0
        for txn in queryset:
            for match in txn.matches.filter(status="needs_review"):
                try:
                    confirm_match(match)
                    confirmed += 1
                except ValueError:
                    pass
        self.message_user(request, f"{confirmed} match(es) confirmed.")

    @admin.action(description="Reject all matches for selected transactions")
    def action_reject_matches(self, request, queryset):
        """Reject every non-locked Match attached to the selected transactions."""
        rejected = 0
        for txn in queryset:
            for match in txn.matches.exclude(status__in=["confirmed", "manually_matched"]).filter(locked_by_user=False):
                try:
                    reject_match(match)
                    rejected += 1
                except ValueError:
                    pass
        self.message_user(request, f"{rejected} match(es) rejected.", messages.WARNING)

    @admin.action(description="Mark selected transactions as unrelated")
    def action_mark_unrelated(self, request, queryset):
        """Mark the first unlocked match on each selected transaction as unrelated."""
        marked = 0
        for txn in queryset:
            for match in txn.matches.filter(locked_by_user=False):
                mark_match_unrelated(match)
                marked += 1
                break  # one match per transaction is enough to flip status
        self.message_user(request, f"{marked} transaction(s) marked unrelated.")

    # ------------------------------------------------------------------
    # Dashboard view
    # ------------------------------------------------------------------

    def _dashboard_view(self, request):
        """Two-table reconciliation dashboard with date-range and customer filters.

        POST: handle per-row confirm / reject / unrelated actions.
        GET: render the dashboard with filtered match tables.
        """
        if request.method == "POST":
            action = request.POST.get("action")
            match_id = request.POST.get("match_id")

            if action == "upload_and_reconcile":
                f = request.FILES.get("file")
                if not f:
                    messages.error(request, "No file selected.")
                elif f.size > MAX_UPLOAD_BYTES:
                    messages.error(request, f"File too large ({f.size} bytes). Max 20 MB.")
                else:
                    ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
                    try:
                        raw = f.read().decode("utf-8")
                        if ext == "json":
                            summary = ingest_transactions(raw, f.name)
                        elif ext == "csv":
                            summary = ingest_payout(raw, f.name)
                        else:
                            raise ValueError(f"Unsupported file type '.{ext}'. Expected .json or .csv.")
                        detail = ", ".join(f"{k}: {v}" for k, v in summary.items())
                        messages.success(request, f"Uploaded {f.name} — {detail}")
                        run = run_reconciliation()
                        messages.success(
                            request,
                            f"Reconciliation complete — {run.total_processed} processed, "
                            f"{run.auto_matched_count} auto-matched, {run.needs_review_count} need review.",
                        )
                    except Exception as exc:
                        messages.error(request, str(exc))

            elif action and match_id:
                try:
                    match = Match.objects.get(pk=match_id)
                    if action == "confirm":
                        confirm_match(match)
                        messages.success(request, f"Match #{match_id} confirmed.")
                    elif action == "reject":
                        reject_match(match)
                        messages.warning(request, f"Match #{match_id} rejected.")
                    elif action == "unrelated":
                        mark_match_unrelated(match)
                        messages.info(request, "Transaction marked as unrelated.")
                except Match.DoesNotExist:
                    messages.error(request, f"Match #{match_id} not found.")
                except ValueError as exc:
                    messages.error(request, str(exc))

            params = {k: request.POST[k] for k in ("date_from", "date_to", "customer")
                      if request.POST.get(k)}
            redirect_url = reverse("admin:reconciler-dashboard")
            if params:
                redirect_url += "?" + urlencode(params)
            return HttpResponseRedirect(redirect_url)

        from datetime import date
        from django.db.models import Min, Q

        today = date.today()
        customer_id = request.GET.get("customer", "")
        customer_obj = Customer.objects.filter(customer_id=customer_id).first() if customer_id else None

        # Customer filter — built once, reused for both the min-date lookup and the main queries.
        # needs_review: OR with raw_counterparty because unmatched matches have invoice=null.
        # reconciled: strict invoice→customer path only.
        if customer_obj:
            by_invoice = Q(invoice__customer__customer_id=customer_id)
            by_counterparty = Q(invoice__isnull=True, transaction__raw_counterparty__icontains=customer_obj.name)
            needs_review_filter = by_invoice | by_counterparty
            reconciled_filter = by_invoice
        else:
            needs_review_filter = Q()
            reconciled_filter = Q()

        # Default date_from: earliest transaction date visible under the current customer filter.
        if request.GET.get("date_from"):
            date_from = request.GET["date_from"]
        else:
            earliest = (
                Match.objects.filter(needs_review_filter | reconciled_filter)
                .aggregate(min_date=Min("transaction__date"))["min_date"]
            )
            date_from = earliest.isoformat() if earliest else today.isoformat()

        date_to = request.GET.get("date_to") or today.isoformat()

        base_qs = Match.objects.select_related(
            "transaction", "transaction__currency",
            "invoice", "invoice__customer",
        )
        if date_from:
            base_qs = base_qs.filter(transaction__date__gte=date_from)
        if date_to:
            base_qs = base_qs.filter(transaction__date__lte=date_to)

        needs_review = list(
            base_qs.filter(status="needs_review").filter(needs_review_filter)
            .order_by("transaction__date", "transaction_id")[:200]
        )
        reconciled = list(
            base_qs.filter(status__in=["auto_matched", "confirmed", "manually_matched"])
            .filter(reconciled_filter)
            .order_by("-transaction__date")[:200]
        )
        customers = Customer.objects.order_by("name")

        context = {
            **self.admin_site.each_context(request),
            "title": "Reconciliation Dashboard",
            "needs_review": needs_review,
            "reconciled": reconciled,
            "customers": customers,
            "filter_date_from": date_from,
            "filter_date_to": date_to,
            "filter_customer": customer_id,
        }
        return render(request, "admin/reconciler/dashboard.html", context)


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
