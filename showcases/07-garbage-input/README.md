# Showcase 07 — Garbage Input

Demonstrates how the system rejects completely invalid files before touching the database. No records are created, no reconciliation runs, and a clear error message is returned.

## What's in the files

| File | What it is | Expected error |
|---|---|---|
| `not_json.txt` | Plain text file | `Expected a .json file` (file extension check in Admin) |
| `broken.json` | Truncated JSON — unclosed object | `Invalid JSON: ...` |
| `object_not_array.json` | Valid JSON but a single object, not an array | `Expected a JSON array of invoice objects.` |
| `wrong_columns.csv` | CSV with wrong column names for payout upload | `CSV missing required columns: {...}` |

## Where each error fires

### File extension check (Django Admin upload bar and IngestionEventAdmin views)

The Admin upload handlers check the file extension before calling the service:

```
# Dashboard upload bar: checks .json vs .csv by extension
# IngestionEventAdmin views: checks exact extension per route
```

Uploading `not_json.txt` to any endpoint → rejected immediately, no `IngestionEvent` created.

### JSON parse error (`broken.json`)

`ingest_invoices` / `ingest_transactions` calls `json.loads()`. On failure:

```python
raise ValueError(f"Invalid JSON: {exc}")
```

An `IngestionEvent` with `status=failed` is written so the error is visible in the Ingestion Events log.

### Wrong root type (`object_not_array.json`)

After parsing, the service checks `isinstance(records, list)`:

```python
raise ValueError("Expected a JSON array of invoice objects.")
```

Same result: `IngestionEvent` with `status=failed`.

### Wrong CSV columns (`wrong_columns.csv`)

`ingest_payout` reads the header row and checks for all required columns:

```python
required = {"charge_id", "invoice_id", "customer_name", "gross_amount", "fee", "net_amount", "type"}
missing = required - set(reader.fieldnames or [])
raise ValueError(f"CSV missing required columns: {missing}")
```

`IngestionEvent` with `status=failed`.

## Steps

### Via Django Admin

1. Open `/admin/`
2. Try uploading each file to the appropriate endpoint:
   - `not_json.txt` → **Ingestion Events → Upload Transactions**
   - `broken.json` → **Ingestion Events → Upload Transactions**
   - `object_not_array.json` → **Ingestion Events → Upload Invoices**
   - `wrong_columns.csv` → **Ingestion Events → Upload Payout CSV**
3. Observe the error banner on each attempt
4. Open **Ingestion Events** — failed events are recorded for `broken.json`, `object_not_array.json`, and `wrong_columns.csv` (the `.txt` file is rejected before an event is created)

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/transactions/ -F "file=@broken.json"
# → 400 {"detail": "Invalid JSON: ..."}

curl -X POST $BASE/ingest/invoices/ -F "file=@object_not_array.json"
# → 400 {"detail": "Expected a JSON array of invoice objects."}

curl -X POST $BASE/ingest/payout/ -F "file=@wrong_columns.csv"
# → 400 {"detail": "CSV missing required columns: {...}"}
```

## Expected result

No invoices, transactions, or matches are created. The database is left unchanged. The only side effect is a failed `IngestionEvent` record in the log (except for `not_json.txt` which is blocked before reaching the service).
