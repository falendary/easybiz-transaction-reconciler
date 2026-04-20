from django.db import connection
from django.db.utils import OperationalError
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import api_view
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from reconciler.ingestion_service import ingest_invoices, ingest_payout, ingest_transactions

from reconciler.filters import (
    AccountEntryFilter,
    CounterpartyFilter,
    InvoiceFilter,
    MatchFilter,
    TransactionFilter,
)
from reconciler.models import (
    AccountEntry,
    Counterparty,
    Currency,
    Customer,
    FXRate,
    IngestionEvent,
    Invoice,
    Match,
    ReconciliationRun,
    Transaction,
)
from reconciler.serializers import (
    AccountEntrySerializer,
    CounterpartySerializer,
    CurrencySerializer,
    CustomerDetailSerializer,
    CustomerListSerializer,
    FXRateSerializer,
    IngestionEventDetailSerializer,
    IngestionEventSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    MatchSerializer,
    ReconciliationRunSerializer,
    TransactionDetailSerializer,
    TransactionListSerializer,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@extend_schema(
    summary="Health check",
    description="Returns 200 if the API and database are reachable.",
    responses={200: {"type": "object", "properties": {"status": {"type": "string"}, "database": {"type": "string"}}}},
)
@api_view(["GET"])
def health_check(request):
    """Check API and database connectivity."""
    try:
        connection.ensure_connection()
        db_status = "ok"
    except OperationalError:
        db_status = "unavailable"
    return Response({"status": "ok", "database": db_status})


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@extend_schema_view(list=extend_schema(summary="List currencies"))
class CurrencyViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only list of active ISO 4217 currencies."""

    queryset = Currency.objects.filter(is_active=True).order_by("code")
    serializer_class = CurrencySerializer


@extend_schema_view(
    list=extend_schema(summary="List FX rates"),
    create=extend_schema(summary="Create FX rate"),
)
class FXRateViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """FX rates filterable by base, quote, and date."""

    queryset = FXRate.objects.select_related("base_currency", "quote_currency").order_by("-date")
    serializer_class = FXRateSerializer
    filterset_fields = ["base_currency__code", "quote_currency__code", "date", "source"]


# ---------------------------------------------------------------------------
# Customers & Counterparties
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List customers"),
    retrieve=extend_schema(summary="Customer detail with accounts and reconciliation balance"),
)
class CustomerViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Customers parsed from invoices. Detail includes account balances."""

    queryset = Customer.objects.prefetch_related("accounts").order_by("customer_id")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CustomerDetailSerializer
        return CustomerListSerializer


@extend_schema_view(
    list=extend_schema(summary="List counterparties"),
    partial_update=extend_schema(summary="Link counterparty to a customer"),
)
class CounterpartyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Bank counterparty names. Use PATCH to link a counterparty to a customer."""

    queryset = Counterparty.objects.select_related("customer").order_by("normalized_name")
    serializer_class = CounterpartySerializer
    filterset_class = CounterpartyFilter
    http_method_names = ["get", "patch", "head", "options"]


# ---------------------------------------------------------------------------
# Ingestion events
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List ingestion events"),
    retrieve=extend_schema(summary="Ingestion event detail (add ?include_raw=true for raw content)"),
)
class IngestionEventViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Audit log of all file uploads."""

    queryset = IngestionEvent.objects.select_related("source").order_by("-uploaded_at")
    filterset_fields = ["file_type", "status"]

    def get_serializer_class(self):
        if self.action == "retrieve" and self.request.query_params.get("include_raw"):
            return IngestionEventDetailSerializer
        return IngestionEventSerializer


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List invoices and credit notes"),
    retrieve=extend_schema(summary="Invoice detail with line items and matches"),
)
class InvoiceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Invoices filterable by status, type, and customer_id."""

    queryset = Invoice.objects.select_related("customer", "currency").order_by("-issue_date")
    filterset_class = InvoiceFilter

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InvoiceDetailSerializer
        return InvoiceListSerializer

    def get_queryset(self):
        if self.action == "retrieve":
            return Invoice.objects.select_related("customer", "currency").prefetch_related(
                "line_items", "matches__transaction"
            )
        return self.queryset


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List transactions"),
    retrieve=extend_schema(summary="Transaction detail with matches and payout lines"),
)
class TransactionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Bank transactions filterable by reconciliation_status and is_duplicate."""

    queryset = Transaction.objects.select_related("currency").order_by("-date")
    filterset_class = TransactionFilter

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TransactionDetailSerializer
        return TransactionListSerializer

    def get_queryset(self):
        if self.action == "retrieve":
            return Transaction.objects.select_related("currency").prefetch_related(
                "payout_lines", "matches__invoice"
            )
        return self.queryset


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List matches"),
    retrieve=extend_schema(summary="Match detail"),
)
class MatchViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Reconciliation matches filterable by status, match_type, and transaction_id."""

    queryset = Match.objects.select_related(
        "transaction", "invoice", "performed_by"
    ).order_by("-created_at")
    serializer_class = MatchSerializer
    filterset_class = MatchFilter


# ---------------------------------------------------------------------------
# Account entries
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List account entries"),
    retrieve=extend_schema(summary="Account entry detail"),
)
class AccountEntryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Double-entry ledger lines. Filterable by account_type and customer_id."""

    queryset = AccountEntry.objects.select_related(
        "account__customer", "match", "invoice", "transaction"
    ).order_by("-created_at")
    serializer_class = AccountEntrySerializer
    filterset_class = AccountEntryFilter


# ---------------------------------------------------------------------------
# Reconciliation runs
# ---------------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(summary="List reconciliation runs"),
    retrieve=extend_schema(summary="Reconciliation run detail"),
)
class ReconciliationRunViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """History of all reconciliation runs."""

    queryset = ReconciliationRun.objects.order_by("-started_at")
    serializer_class = ReconciliationRunSerializer


# ---------------------------------------------------------------------------
# File upload (ingestion)
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


def _read_upload(request, allowed_extensions: list[str]) -> tuple[str, str]:
    """Extract and validate an uploaded file from the request.

    Returns:
        (raw_content, filename) tuple

    Raises:
        ValueError: if file is missing, too large, or has wrong extension
    """
    file = request.FILES.get("file")
    if not file:
        raise ValueError("No file provided. Send the file as multipart/form-data with key 'file'.")
    if file.size > MAX_UPLOAD_BYTES:
        raise ValueError(f"File too large ({file.size} bytes). Maximum is 20 MB.")
    ext = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
    if ext not in allowed_extensions:
        raise ValueError(f"Unsupported file type '.{ext}'. Expected: {allowed_extensions}.")
    return file.read().decode("utf-8"), file.name


@extend_schema(
    summary="Upload invoices JSON",
    description="Accepts invoices.json. Upserts on invoice_id — re-uploading is safe.",
    request={"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}},
    responses={200: {"type": "object"}},
)
class IngestInvoicesView(APIView):
    """Upload and parse invoices.json. Idempotent on invoice_id."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        """Accept invoices.json, upsert all records, return ingestion summary."""
        try:
            raw_content, filename = _read_upload(request, ["json"])
            result = ingest_invoices(raw_content, filename)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


@extend_schema(
    summary="Upload transactions JSON",
    description="Accepts transactions.json. Upserts on transaction_id. [RE-IMPORTED] prefix sets is_duplicate=true.",
    request={"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}},
    responses={200: {"type": "object"}},
)
class IngestTransactionsView(APIView):
    """Upload and parse transactions.json. Idempotent on transaction_id."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        """Accept transactions.json, upsert all records, return ingestion summary."""
        try:
            raw_content, filename = _read_upload(request, ["json"])
            result = ingest_transactions(raw_content, filename)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)


@extend_schema(
    summary="Upload Stripe payout CSV",
    description=(
        "Accepts a Stripe payout CSV. Links each charge line to its parent Transaction "
        "via the payout ID in structured_reference. Transactions must be uploaded first."
    ),
    request={"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}}},
    responses={200: {"type": "object"}},
)
class IngestPayoutView(APIView):
    """Upload and parse payout_report.csv. Idempotent on charge_id."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        """Accept payout CSV, create PayoutLine records linked to parent transaction."""
        try:
            raw_content, filename = _read_upload(request, ["csv"])
            result = ingest_payout(raw_content, filename)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_200_OK)
