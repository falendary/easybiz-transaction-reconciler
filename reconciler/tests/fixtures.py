"""Shared test fixtures and helpers used across all test modules."""
import io
import json

from django.urls import reverse

from reconciler.models import Currency, Customer, IngestionEvent, Source


# ---------------------------------------------------------------------------
# Raw payloads
# ---------------------------------------------------------------------------

INVOICE_RECORD = {
    "id": "INV-TEST-0001",
    "type": "invoice",
    "customer_id": "CUST-T01",
    "customer_name": "Test Client S.à r.l.",
    "customer_vat": "LU99999999",
    "issue_date": "2026-02-01",
    "due_date": "2026-03-01",
    "currency": "EUR",
    "line_items": [
        {
            "line_id": "INV-TEST-0001-L1",
            "description": "Bookkeeping",
            "quantity": 1,
            "unit_price": "100.00",
            "tax_rate": "0.17",
            "amount": "117.00",
        }
    ],
    "subtotal": "100.00",
    "tax_total": "17.00",
    "total": "117.00",
}

CREDIT_NOTE_RECORD = {
    "id": "CN-TEST-0001",
    "type": "credit_note",
    "customer_id": "CUST-T01",
    "customer_name": "Test Client S.à r.l.",
    "customer_vat": "LU99999999",
    "issue_date": "2026-02-10",
    "due_date": "2026-03-10",
    "currency": "EUR",
    "line_items": [],
    "subtotal": "-50.00",
    "tax_total": "-8.50",
    "total": "-58.50",
}

TRANSACTION_RECORD = {
    "id": "TXN-TEST-0001",
    "date": "2026-02-26",
    "amount": "117.00",
    "currency": "EUR",
    "counterparty_name": "Test Client",
    "structured_reference": "INV-TEST-0001",
    "description": "Payment INV-TEST-0001",
}

DUPLICATE_TRANSACTION_RECORD = {
    "id": "TXN-TEST-0002",
    "date": "2026-02-26",
    "amount": "117.00",
    "currency": "EUR",
    "counterparty_name": "Test Client",
    "structured_reference": "INV-TEST-0001",
    "description": "[RE-IMPORTED] Payment INV-TEST-0001",
}

PAYOUT_TRANSACTION_RECORD = {
    "id": "TXN-PAYOUT-001",
    "date": "2026-02-28",
    "amount": "113.56",
    "currency": "EUR",
    "counterparty_name": "STRIPE PAYMENTS LUXEMBOURG",
    "structured_reference": "po_TESTPAYOUT",
    "description": "Stripe payout po_TESTPAYOUT",
}

PAYOUT_CSV = (
    "charge_id,invoice_id,customer_name,gross_amount,fee,net_amount,type\n"
    "ch_TEST1,INV-TEST-0001,Test Client S.à r.l.,117.00,3.44,113.56,charge\n"
    "po_TESTPAYOUT,,PAYOUT TOTAL,,,113.56,payout\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def upload(client, url_name: str, content: str, filename: str):
    """POST a file upload to the given named URL."""
    file = io.BytesIO(content.encode())
    file.name = filename
    return client.post(reverse(url_name), {"file": file}, format="multipart")


def make_currency(code: str = "EUR") -> Currency:
    currency, _ = Currency.objects.get_or_create(
        code=code, defaults={"name": code, "symbol": code, "decimal_places": 2}
    )
    return currency


def make_source(name: str = "Demo CRM", source_type: str = "crm") -> Source:
    source, _ = Source.objects.get_or_create(name=name, defaults={"source_type": source_type})
    return source


def make_ingestion_event(file_type: str = "invoices") -> IngestionEvent:
    return IngestionEvent.objects.create(
        file_type=file_type,
        filename=f"{file_type}.json",
        raw_content="[]",
        status="success",
        source=make_source(),
    )


def make_customer(customer_id: str = "CUST-T01", name: str = "Test Client") -> Customer:
    customer, _ = Customer.objects.get_or_create(
        customer_id=customer_id, defaults={"name": name}
    )
    return customer
