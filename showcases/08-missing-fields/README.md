# Showcase 08 — Missing Required Fields

Demonstrates partial ingestion: the JSON is valid and parses correctly, but individual records are missing fields the service needs. Some records are skipped with per-row errors, others crash the whole batch with an unhandled `KeyError`.

## What's in the files

| File | What's missing | Behaviour |
|---|---|---|
| `invoices_no_id.json` | `id` field | Row skipped, recorded in `errors[]`, rest of batch continues |
| `invoices_no_customer.json` | `customer_id` field | Unhandled `KeyError` — entire batch rolled back |
| `transactions_no_id.json` | `id` field | Row skipped, recorded in `errors[]`, rest of batch continues |
| `transactions_no_date.json` | `date` field | Unhandled `KeyError` — entire batch rolled back |

## Why the behaviour differs

The ingestion service has an **explicit null-check only for `id`**:

```python
invoice_id = record.get("id")
if not invoice_id:
    errors.append({"index": idx, "error": "missing id field"})
    continue   # ← skip this row, keep going
```

All other required fields (`customer_id`, `issue_date`, `due_date`, `date`) are accessed with direct key lookup (`record["customer_id"]`). If the key is absent, Python raises a `KeyError`, which is caught by the outer `except Exception` block, rolls back the entire atomic transaction, sets `IngestionEvent.status=failed`, and re-raises as a 400 error.

This is the current behaviour — a validation gap documented in `DECISIONS.md`. A production-grade service would validate all required fields upfront and return structured per-row errors for all of them.

## Steps

### Via Django Admin

1. Open `/admin/`

**Missing id — row skipped:**

2. **Ingestion Events → Upload Invoices** — upload `invoices_no_id.json`
3. Upload succeeds with `created: 0, errors: [{index: 0, error: "missing id field"}]`
4. No invoice record is created

**Missing customer_id — batch fails:**

5. **Ingestion Events → Upload Invoices** — upload `invoices_no_customer.json`
6. Error banner: `KeyError: 'customer_id'`
7. Open **Ingestion Events** — event has `status=failed`
8. No invoice records are created (transaction rolled back)

**Missing id on transactions — row skipped:**

9. **Ingestion Events → Upload Transactions** — upload `transactions_no_id.json`
10. Upload succeeds with `created: 0, errors: [{index: 0, error: "missing id field"}]`

**Missing date on transactions — batch fails:**

11. **Ingestion Events → Upload Transactions** — upload `transactions_no_date.json`
12. Error banner: `KeyError: 'date'`
13. Open **Ingestion Events** — event has `status=failed`

### Via API

```bash
BASE=http://localhost:8000/api

# Row skipped — 200 with errors list
curl -X POST $BASE/ingest/invoices/ -F "file=@invoices_no_id.json"
# → 200 {"status": "success", "created": 0, "errors": [{"index": 0, "error": "missing id field"}]}

# Batch fails — 400
curl -X POST $BASE/ingest/invoices/ -F "file=@invoices_no_customer.json"
# → 400 {"detail": "'customer_id'"}

# Row skipped — 200 with errors list
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions_no_id.json"
# → 200 {"status": "success", "created": 0, "errors": [{"index": 0, "error": "missing id field"}]}

# Batch fails — 400
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions_no_date.json"
# → 400 {"detail": "'date'"}
```

## What this reveals

The service has inconsistent validation coverage. `id` is explicitly guarded; everything else is not. The fix would be a validation pass at the top of each record loop before any database writes — collecting all field errors before deciding whether to skip or abort.
