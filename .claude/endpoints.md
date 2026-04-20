# API Endpoints — EasyBiz Reconciler

Base URL: `http://localhost:8000/api`
Documentation: `http://localhost:8000/api/docs/` (Swagger UI via drf-spectacular)
All requests and responses are `application/json` unless noted.
All monetary values are strings in decimal notation — e.g. `"1123.20"`.
All dates are ISO 8601 — e.g. `"2026-02-21"`.

---

## Reference Data

### Currency

#### `GET /currencies/`
List all active currencies.

**Response**
```json
[
  {
    "id": 1,
    "code": "EUR",
    "name": "Euro",
    "symbol": "€",
    "decimal_places": 2,
    "is_active": true
  }
]
```

---

### FX Rates

#### `GET /fx-rates/`
List all FX rates. Filterable by `?base=EUR&quote=USD&date=2026-02-28`.

**Response**
```json
[
  {
    "id": 1,
    "base_currency": "EUR",
    "quote_currency": "USD",
    "rate": "1.0850",
    "date": "2026-02-28",
    "source": "fixed_demo"
  }
]
```

#### `POST /fx-rates/`
Create a new FX rate manually.

**Request**
```json
{
  "base_currency": "EUR",
  "quote_currency": "USD",
  "rate": "1.0850",
  "date": "2026-02-28",
  "source": "fixed_demo"
}
```

---

### Customers

#### `GET /customers/`
List all customers.

**Response**
```json
[
  {
    "id": 1,
    "customer_id": "CUST-001",
    "name": "Acme S.à r.l.",
    "vat_number": "LU12345678",
    "address": null,
    "created_at": "2026-04-20T10:00:00Z"
  }
]
```

#### `GET /customers/<id>/`
Customer detail with linked accounts and reconciliation balance.

**Response**
```json
{
  "id": 1,
  "customer_id": "CUST-001",
  "name": "Acme S.à r.l.",
  "vat_number": "LU12345678",
  "address": null,
  "accounts": [
    { "id": 1, "account_type": "receivable", "currency": "EUR" },
    { "id": 2, "account_type": "bank", "currency": "EUR" }
  ],
  "reconciliation_balance": "0.00",
  "created_at": "2026-04-20T10:00:00Z"
}
```

---

### Counterparties

#### `GET /counterparties/`
List all counterparties. Filterable by `?linked=true` (has a customer FK) or `?linked=false`.

**Response**
```json
[
  {
    "id": 1,
    "raw_name": "INITECHLUXEMBOURGSARL",
    "normalized_name": "Initech Luxembourg SARL",
    "customer": { "id": 3, "customer_id": "CUST-003", "name": "Initech Luxembourg SARL" },
    "description": null,
    "created_at": "2026-04-20T10:00:00Z"
  }
]
```

#### `PATCH /counterparties/<id>/`
Manually link a counterparty to a customer or add a description.

**Request**
```json
{
  "customer_id": 3,
  "description": "Pays via SEPA credit transfer"
}
```

---

## Ingestion

### `POST /ingest/invoices/`
Upload and parse `invoices.json`. Idempotent — re-uploading is safe.
Content-Type: `multipart/form-data`

**Request**
```
file: invoices.json
```

**Response**
```json
{
  "ingestion_event_id": 1,
  "status": "success",
  "created": 48,
  "updated": 2,
  "skipped": 0,
  "errors": []
}
```

---

### `POST /ingest/transactions/`
Upload and parse `transactions.json`. Idempotent — re-uploading is safe.
Duplicate transactions (same id, date, amount, reference) are flagged with `is_duplicate: true`.
Content-Type: `multipart/form-data`

**Request**
```
file: transactions.json
```

**Response**
```json
{
  "ingestion_event_id": 2,
  "status": "success",
  "created": 75,
  "updated": 0,
  "duplicates_flagged": 5,
  "errors": []
}
```

---

### `POST /ingest/payout/`
Upload and parse a Stripe payout CSV. Idempotent — re-uploading is safe.
Links PayoutLines to their parent Transaction via payout reference in `structured_reference`.
Content-Type: `multipart/form-data`

**Request**
```
file: payout_report.csv
```

**Response**
```json
{
  "ingestion_event_id": 3,
  "status": "success",
  "payout_id": "po_1NfK2r2026EasyBiz",
  "parent_transaction": "TXN-0043",
  "lines_created": 7,
  "errors": []
}
```

---

### `GET /ingest/events/`
List all ingestion events for audit.

**Response**
```json
[
  {
    "id": 1,
    "file_type": "invoices",
    "filename": "invoices.json",
    "uploaded_at": "2026-04-20T10:00:00Z",
    "status": "success",
    "error_message": null
  }
]
```

#### `GET /ingest/events/<id>/`
Ingestion event detail. Does not return `raw_content` by default — add `?include_raw=true` if needed.

---

## Invoices

### `GET /invoices/`
List all invoices and credit notes. Filterable by `?status=open&type=invoice&customer_id=CUST-001`.

**Response**
```json
[
  {
    "id": 1,
    "invoice_id": "INV-2026-0001",
    "type": "invoice",
    "customer": { "id": 1, "name": "Acme S.à r.l." },
    "issue_date": "2026-02-21",
    "due_date": "2026-03-23",
    "currency": "EUR",
    "subtotal": "960.00",
    "tax_total": "163.20",
    "total": "1123.20",
    "status": "paid",
    "force_close_note": null
  }
]
```

### `GET /invoices/<id>/`
Invoice detail with line items and linked matches.

**Response**
```json
{
  "id": 1,
  "invoice_id": "INV-2026-0001",
  "type": "invoice",
  "customer": { "id": 1, "name": "Acme S.à r.l." },
  "issue_date": "2026-02-21",
  "due_date": "2026-03-23",
  "currency": "EUR",
  "subtotal": "960.00",
  "tax_total": "163.20",
  "total": "1123.20",
  "status": "paid",
  "force_close_note": null,
  "line_items": [
    {
      "line_id": "INV-2026-0001-L1",
      "description": "AML/KYC review",
      "quantity": "3.00",
      "unit_price": "320.00",
      "tax_rate": "0.17",
      "amount": "1123.20"
    }
  ],
  "matches": [
    {
      "id": 1,
      "transaction_id": "TXN-0001",
      "allocated_amount": "1123.20",
      "confidence_score": "0.95",
      "match_type": "exact",
      "status": "confirmed"
    }
  ]
}
```

### `POST /invoices/<id>/force-close/`
Force-close a partially paid invoice regardless of outstanding balance.
Sets `status: force_closed`. Requires a non-empty note. Sets `locked_by_user: true` on all linked matches.

**Request**
```json
{
  "note": "Client confirmed settlement via separate arrangement"
}
```

**Response**
```json
{
  "id": 1,
  "invoice_id": "INV-2026-0026",
  "status": "force_closed",
  "force_close_note": "Client confirmed settlement via separate arrangement"
}
```

---

## Transactions

### `GET /transactions/`
List all transactions. Filterable by `?reconciliation_status=needs_review&is_duplicate=false`.

**Response**
```json
[
  {
    "id": 1,
    "transaction_id": "TXN-0001",
    "date": "2026-02-26",
    "amount": "1123.20",
    "currency": "EUR",
    "raw_counterparty": "Acme Sarl",
    "structured_reference": "INV-2026-0001",
    "description": "Payment INV-2026-0001",
    "is_duplicate": false,
    "reconciliation_status": "reconciled",
    "locked_by_user": false
  }
]
```

### `GET /transactions/<id>/`
Transaction detail with linked matches and payout lines if applicable.

**Response**
```json
{
  "id": 43,
  "transaction_id": "TXN-0043",
  "date": "2026-03-15",
  "amount": "2720.73",
  "currency": "EUR",
  "raw_counterparty": "STRIPE PAYMENTS LUXEMBOURG",
  "structured_reference": "po_1NfK2r2026EasyBiz",
  "description": "Stripe payout — see report po_1NfK2r2026EasyBiz",
  "is_duplicate": false,
  "reconciliation_status": "reconciled",
  "locked_by_user": false,
  "payout_lines": [
    {
      "charge_id": "ch_30NfK",
      "raw_invoice_id": "INV-2026-0045",
      "gross_amount": "526.50",
      "fee": "15.52",
      "net_amount": "510.98",
      "type": "charge"
    }
  ],
  "matches": [
    {
      "id": 10,
      "invoice_id": "INV-2026-0045",
      "allocated_amount": "510.98",
      "confidence_score": "0.95",
      "match_type": "payout",
      "status": "auto_matched"
    }
  ]
}
```

---

## Reconciliation

### `POST /reconcile/`
Trigger a reconciliation run. Processes all transactions where `locked_by_user: false`.
Skips records where `locked_by_user: true`.
Idempotent — running twice produces the same result.
Synchronous — returns when complete.

**Request**
```json
{}
```

**Response**
```json
{
  "run_id": 1,
  "status": "completed",
  "started_at": "2026-04-20T10:05:00Z",
  "finished_at": "2026-04-20T10:05:03Z",
  "total_processed": 80,
  "auto_matched_count": 58,
  "needs_review_count": 12,
  "skipped_locked_count": 10
}
```

### `GET /reconcile/runs/`
List all reconciliation runs.

**Response**
```json
[
  {
    "id": 1,
    "status": "completed",
    "started_at": "2026-04-20T10:05:00Z",
    "finished_at": "2026-04-20T10:05:03Z",
    "total_processed": 80,
    "auto_matched_count": 58,
    "needs_review_count": 12,
    "skipped_locked_count": 10
  }
]
```

### `GET /reconcile/runs/<id>/`
Reconciliation run detail with per-transaction breakdown.

---

## Matches

### `GET /matches/`
List all matches. Filterable by `?status=needs_review&transaction_id=TXN-0043`.

**Response**
```json
[
  {
    "id": 1,
    "transaction": { "id": 1, "transaction_id": "TXN-0001", "amount": "1123.20" },
    "invoice": { "id": 1, "invoice_id": "INV-2026-0001", "total": "1123.20" },
    "allocated_amount": "1123.20",
    "confidence_score": "0.95",
    "match_type": "exact",
    "status": "auto_matched",
    "locked_by_user": false,
    "note": null,
    "created_at": "2026-04-20T10:05:00Z",
    "updated_at": "2026-04-20T10:05:00Z"
  }
]
```

### `GET /matches/<id>/`
Match detail.

### `POST /matches/`
Create a manual match between a transaction and one or more invoices.
Sets `locked_by_user: true` automatically.
Allocated amounts must sum to the transaction total.

**Request**
```json
{
  "transaction_id": 30,
  "allocations": [
    { "invoice_id": 28, "allocated_amount": "468.00" },
    { "invoice_id": 29, "allocated_amount": "468.00" },
    { "invoice_id": 30, "allocated_amount": "468.00" }
  ],
  "note": "Consolidated payment confirmed by client email"
}
```

**Response**
```json
[
  {
    "id": 101,
    "transaction_id": "TXN-0030",
    "invoice_id": "INV-2026-0028",
    "allocated_amount": "468.00",
    "match_type": "manually_matched",
    "status": "manually_matched",
    "locked_by_user": true
  }
]
```

### `POST /matches/<id>/confirm/`
Confirm an auto-matched or needs_review match.
Sets `status: confirmed` and `locked_by_user: true`.

**Request**
```json
{
  "note": "Verified against client remittance advice"
}
```

**Response**
```json
{
  "id": 1,
  "status": "confirmed",
  "locked_by_user": true
}
```

### `POST /matches/<id>/reject/`
Reject a match. Sets `status: rejected` and `locked_by_user: true`.
Transaction returns to `needs_review`.

**Request**
```json
{
  "note": "Wrong invoice — client paid a different period"
}
```

**Response**
```json
{
  "id": 1,
  "status": "rejected",
  "locked_by_user": true
}
```

### `POST /matches/<id>/mark-unrelated/`
Mark a transaction as unrelated to any invoice (noise).
Sets `status: unrelated` and `locked_by_user: true`.

**Request**
```json
{
  "note": "Salary payment — not an invoice settlement"
}
```

**Response**
```json
{
  "id": 1,
  "status": "unrelated",
  "locked_by_user": true
}
```

### `DELETE /matches/<id>/`
Delete a match and unlock the transaction.
Sets `transaction.locked_by_user: false` and `transaction.reconciliation_status: needs_review`.
Triggers `Invoice.status` recomputation.
Only allowed if `locked_by_user: false` — locked matches cannot be deleted without unlocking first.

### `POST /matches/<id>/unlock/`
Unlock a human-locked match, making it eligible for re-reconciliation.
Sets `locked_by_user: false`. Does not change status.
Requires explicit confirmation — destructive action.

**Request**
```json
{
  "note": "Unlocking for re-review — original assignment was incorrect"
}
```

---

## Account Entries

### `GET /account-entries/`
List all ledger entries. Filterable by `?account_type=receivable&customer_id=1`.

**Response**
```json
[
  {
    "id": 1,
    "account": { "id": 1, "account_type": "receivable", "customer": "Acme S.à r.l." },
    "match": { "id": 1 },
    "invoice": { "id": 1, "invoice_id": "INV-2026-0001" },
    "transaction": null,
    "amount": "-1123.20",
    "entry_type": "credit",
    "created_at": "2026-04-20T10:05:00Z"
  }
]
```

### `GET /account-entries/<id>/`
Account entry detail.

---

## Health

### `GET /health/`
Basic health check. Returns 200 if the API and database are reachable.

**Response**
```json
{
  "status": "ok",
  "database": "ok"
}
```

---

## Error Responses

All endpoints return standard error shapes:

**400 Bad Request**
```json
{
  "error": "validation_error",
  "detail": {
    "allocations": ["Allocated amounts must sum to transaction total: 1404.00"]
  }
}
```

**404 Not Found**
```json
{
  "error": "not_found",
  "detail": "Match with id=999 does not exist"
}
```

**409 Conflict**
```json
{
  "error": "conflict",
  "detail": "Match is locked by user — unlock before modifying"
}
```

**500 Internal Server Error**
```json
{
  "error": "internal_error",
  "detail": "Unexpected error during reconciliation run"
}
```
