"""Ingestion service — parses uploaded files and upserts records into the database.

This module is the only place that reads raw file content and writes
IngestionEvent, Invoice, Transaction, and PayoutLine records.
"""

import csv
import io
import json
from decimal import Decimal

from django.db import transaction as db_transaction

from reconciler.models import (
    Counterparty,
    Currency,
    Customer,
    IngestionEvent,
    Invoice,
    InvoiceLineItem,
    PayoutLine,
    Source,
    Transaction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_source(name: str, source_type: str) -> Source:
    source, _ = Source.objects.get_or_create(name=name, defaults={"source_type": source_type})
    return source


def _get_or_create_currency(code: str) -> Currency:
    currency, _ = Currency.objects.get_or_create(
        code=code,
        defaults={"name": code, "symbol": code, "decimal_places": 2},
    )
    return currency


def _dec(value) -> Decimal:
    """Convert a value to Decimal, defaulting to 0 for empty/None."""
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def ingest_invoices(raw_content: str, filename: str) -> dict:
    """Parse and upsert invoice records from a JSON string.

    Parameters:
        raw_content: JSON string — array of invoice objects
        filename: original upload filename, stored on the IngestionEvent

    Returns:
        dict with keys: ingestion_event_id, status, created, updated, skipped, errors

    Raises:
        ValueError: if content is not valid JSON or not a list
    """
    try:
        records = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(records, list):
        raise ValueError("Expected a JSON array of invoice objects.")

    source = _get_or_create_source("Demo CRM", "crm")
    event = IngestionEvent.objects.create(
        file_type="invoices",
        filename=filename,
        raw_content=raw_content,
        status="pending",
        source=source,
    )

    created = updated = skipped = 0
    errors: list[dict] = []
    seen_ids: set[str] = set()

    try:
        with db_transaction.atomic():
            for idx, record in enumerate(records):
                invoice_id = record.get("id")
                if not invoice_id:
                    errors.append({"index": idx, "error": "missing id field"})
                    continue
                if invoice_id in seen_ids:
                    skipped += 1
                    continue
                seen_ids.add(invoice_id)

                customer, _ = Customer.objects.update_or_create(
                    customer_id=record["customer_id"],
                    defaults={
                        "name": record.get("customer_name", ""),
                        "vat_number": record.get("customer_vat"),
                    },
                )
                currency = _get_or_create_currency(record.get("currency", "EUR"))

                invoice, was_created = Invoice.objects.update_or_create(
                    invoice_id=invoice_id,
                    defaults={
                        "type": record.get("type", "invoice"),
                        "customer": customer,
                        "issue_date": record["issue_date"],
                        "due_date": record["due_date"],
                        "currency": currency,
                        "subtotal": _dec(record.get("subtotal")),
                        "tax_total": _dec(record.get("tax_total")),
                        "total": _dec(record.get("total")),
                        "source": source,
                        "ingestion_event": event,
                    },
                )

                # Replace line items on every upsert to stay in sync with source
                invoice.line_items.all().delete()
                for line in record.get("line_items", []):
                    InvoiceLineItem.objects.create(
                        invoice=invoice,
                        line_id=line.get("line_id", ""),
                        description=line.get("description", ""),
                        quantity=_dec(line.get("quantity", 1)),
                        unit_price=_dec(line.get("unit_price")),
                        tax_rate=_dec(line.get("tax_rate")),
                        amount=_dec(line.get("amount")),
                    )

                if was_created:
                    created += 1
                else:
                    updated += 1

        event.status = "success"
        event.save(update_fields=["status"])

    except Exception as exc:
        event.status = "failed"
        event.error_message = str(exc)
        event.save(update_fields=["status", "error_message"])
        raise

    return {
        "ingestion_event_id": event.id,
        "status": "success",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def ingest_transactions(raw_content: str, filename: str) -> dict:
    """Parse and upsert transaction records from a JSON string.

    Parameters:
        raw_content: JSON string — array of transaction objects
        filename: original upload filename, stored on the IngestionEvent

    Returns:
        dict with keys: ingestion_event_id, status, created, updated, duplicates_flagged, errors

    Raises:
        ValueError: if content is not valid JSON or not a list
    """
    try:
        records = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(records, list):
        raise ValueError("Expected a JSON array of transaction objects.")

    source = _get_or_create_source("ING Bank", "bank")
    event = IngestionEvent.objects.create(
        file_type="transactions",
        filename=filename,
        raw_content=raw_content,
        status="pending",
        source=source,
    )

    created = updated = duplicates_flagged = 0
    errors: list[dict] = []

    try:
        with db_transaction.atomic():
            for idx, record in enumerate(records):
                txn_id = record.get("id")
                if not txn_id:
                    errors.append({"index": idx, "error": "missing id field"})
                    continue

                raw_counterparty = record.get("counterparty_name", "")
                description = record.get("description") or ""
                is_duplicate = description.startswith("[RE-IMPORTED]")

                counterparty, _ = Counterparty.objects.get_or_create(
                    raw_name=raw_counterparty,
                    defaults={"normalized_name": raw_counterparty},
                )
                currency = _get_or_create_currency(record.get("currency", "EUR"))

                _, was_created = Transaction.objects.update_or_create(
                    transaction_id=txn_id,
                    defaults={
                        "date": record["date"],
                        "amount": _dec(record.get("amount")),
                        "currency": currency,
                        "counterparty": counterparty,
                        "raw_counterparty": raw_counterparty,
                        "structured_reference": record.get("structured_reference"),
                        "description": description,
                        "is_duplicate": is_duplicate,
                        "source": source,
                        "ingestion_event": event,
                    },
                )

                if was_created:
                    created += 1
                else:
                    updated += 1

                if is_duplicate:
                    duplicates_flagged += 1

        event.status = "success"
        event.save(update_fields=["status"])

    except Exception as exc:
        event.status = "failed"
        event.error_message = str(exc)
        event.save(update_fields=["status", "error_message"])
        raise

    return {
        "ingestion_event_id": event.id,
        "status": "success",
        "created": created,
        "updated": updated,
        "duplicates_flagged": duplicates_flagged,
        "errors": errors,
    }


def ingest_payout(raw_content: str, filename: str) -> dict:
    """Parse and upsert Stripe payout lines from a CSV string.

    Identifies the parent Transaction by matching the payout row's charge_id
    against Transaction.structured_reference. Creates one PayoutLine per
    non-payout CSV row.

    Parameters:
        raw_content: CSV string with columns: charge_id, invoice_id,
            customer_name, gross_amount, fee, net_amount, type
        filename: original upload filename, stored on the IngestionEvent

    Returns:
        dict with keys: ingestion_event_id, status, payout_id,
            parent_transaction, lines_created, errors

    Raises:
        ValueError: if CSV is malformed, missing required columns, or the
            parent transaction cannot be found
    """
    source = _get_or_create_source("Stripe", "payment_processor")
    event = IngestionEvent.objects.create(
        file_type="payout",
        filename=filename,
        raw_content=raw_content,
        status="pending",
        source=source,
    )

    try:
        reader = csv.DictReader(io.StringIO(raw_content))
        required_columns = {"charge_id", "invoice_id", "customer_name", "gross_amount", "fee", "net_amount", "type"}
        if not required_columns.issubset(set(reader.fieldnames or [])):
            missing = required_columns - set(reader.fieldnames or [])
            raise ValueError(f"CSV missing required columns: {missing}")

        rows = list(reader)

        # Locate the payout row to extract the payout ID
        payout_rows = [r for r in rows if r["type"] == "payout"]
        if not payout_rows:
            raise ValueError("CSV contains no row with type='payout'.")
        payout_id = payout_rows[0]["charge_id"]

        try:
            parent_txn = Transaction.objects.get(structured_reference=payout_id)
        except Transaction.DoesNotExist:
            raise ValueError(
                f"No transaction found with structured_reference='{payout_id}'. "
                "Upload transactions.json first."
            )

        lines_created = 0
        errors: list[dict] = []

        with db_transaction.atomic():
            for row in rows:
                if row["type"] == "payout":
                    continue  # summary row, not a matchable line

                charge_id = row["charge_id"]
                if not charge_id:
                    errors.append({"row": row, "error": "missing charge_id"})
                    continue

                PayoutLine.objects.update_or_create(
                    charge_id=charge_id,
                    defaults={
                        "transaction": parent_txn,
                        "raw_invoice_id": row.get("invoice_id") or None,
                        "customer_name": row.get("customer_name", ""),
                        "gross_amount": _dec(row.get("gross_amount")),
                        "fee": _dec(row.get("fee")),
                        "net_amount": _dec(row.get("net_amount")),
                        "type": row["type"],
                        "ingestion_event": event,
                    },
                )
                lines_created += 1

        event.status = "success"
        event.save(update_fields=["status"])

    except Exception as exc:
        event.status = "failed"
        event.error_message = str(exc)
        event.save(update_fields=["status", "error_message"])
        raise

    return {
        "ingestion_event_id": event.id,
        "status": "success",
        "payout_id": payout_id,
        "parent_transaction": parent_txn.transaction_id,
        "lines_created": lines_created,
        "errors": errors,
    }
