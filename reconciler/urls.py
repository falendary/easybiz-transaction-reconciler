from django.urls import path, include
from rest_framework.routers import DefaultRouter

from reconciler.views import (
    AccountEntryViewSet,
    CounterpartyViewSet,
    CurrencyViewSet,
    CustomerViewSet,
    FXRateViewSet,
    IngestionEventViewSet,
    InvoiceViewSet,
    MatchViewSet,
    ReconciliationRunViewSet,
    TransactionViewSet,
    health_check,
)

router = DefaultRouter()
router.register(r"currencies", CurrencyViewSet, basename="currency")
router.register(r"fx-rates", FXRateViewSet, basename="fxrate")
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"counterparties", CounterpartyViewSet, basename="counterparty")
router.register(r"ingest/events", IngestionEventViewSet, basename="ingestion-event")
router.register(r"invoices", InvoiceViewSet, basename="invoice")
router.register(r"transactions", TransactionViewSet, basename="transaction")
router.register(r"matches", MatchViewSet, basename="match")
router.register(r"account-entries", AccountEntryViewSet, basename="account-entry")
router.register(r"reconcile/runs", ReconciliationRunViewSet, basename="reconciliation-run")

urlpatterns = [
    path("health/", health_check, name="health"),
    path("", include(router.urls)),
]
