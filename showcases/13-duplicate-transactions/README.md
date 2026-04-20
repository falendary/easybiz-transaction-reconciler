# Showcase 13 — Duplicate Transactions

Demonstrates Rule 2: when the same payment is accidentally exported twice from the bank, the second copy arrives with a `[RE-IMPORTED]` prefix in the description. The engine flags it as a duplicate instantly without touching the original match.

## What is a duplicate transaction?

Banks and accounting exports sometimes re-include already-processed transactions in a new export file — usually when a date range overlaps a previous export. The convention is to prefix the description with `[RE-IMPORTED]` to signal that this record already exists.

The ingestion service reads this prefix and sets `is_duplicate=True` on the Transaction. Rule 2 then routes it to `duplicate` status with confidence 1.0 — no invoice is ever linked to it.

## What's in the files

| File | Purpose |
|---|---|
| `invoices.json` | Invoice `SHOWCASE-13-INV-2026-0001` — €585.00 |
| `transactions.json` | Genuine payment `SHOWCASE-13-TXN-2026-0001` — €585.00 |
| `transactions_reimport.json` | Re-exported copy `SHOWCASE-13-TXN-2026-0002` — same amount and reference, description prefixed with `[RE-IMPORTED]` |

## How the engine handles each transaction

| Transaction | Description | `is_duplicate` | Rule | Result |
|---|---|---|---|---|
| TXN-2026-0001 | `Payment SHOWCASE-13-INV-2026-0001` | False | Rule 4 — exact reference + exact amount | auto_matched, confidence 0.95 |
| TXN-2026-0002 | `[RE-IMPORTED] Payment SHOWCASE-13-INV-2026-0001` | True | Rule 2 — duplicate flag | duplicate, confidence 1.0 |

The invoice is paid exactly once. The duplicate transaction never allocates any amount to the invoice.

## What happens on ingestion

`ingest_transactions` checks whether the description starts with `[RE-IMPORTED]`:

```python
is_duplicate = description.startswith("[RE-IMPORTED]")
```

This is set on `Transaction.is_duplicate` at ingestion time. Rule 2 reads this flag and returns immediately without looking for an invoice.

## Steps

### Via Django Admin

**Round 1 — genuine payment**

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard**, filter by `SHOWCASE-13-CUST-001`
6. Observe `SHOWCASE-13-TXN-2026-0001` in the **Reconciled** table, invoice `paid`

**Round 2 — re-import the same payment**

7. **Ingestion Events → Upload Transactions** — upload `transactions_reimport.json`
8. **Reconciliation Runs → Run Reconciliation**
9. Refresh the Dashboard
10. `SHOWCASE-13-TXN-2026-0001` remains in Reconciled, unchanged
11. `SHOWCASE-13-TXN-2026-0002` does **not** appear in either table — it has status `duplicate`, which is excluded from the dashboard views
12. Invoice `SHOWCASE-13-INV-2026-0001` remains `paid` — not double-counted

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/

# Inspect original — expect auto_matched
curl "$BASE/transactions/?reconciliation_status=auto_matched" | python -m json.tool

# Upload the re-import
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions_reimport.json"
curl -X POST $BASE/reconcile/

# Duplicate is flagged — original unchanged
curl "$BASE/transactions/?reconciliation_status=duplicate" | python -m json.tool
```

## Expected result

```
Transaction SHOWCASE-13-TXN-2026-0001
  is_duplicate          : false
  reconciliation_status : auto_matched
  Match → SHOWCASE-13-INV-2026-0001, confidence 0.95

Transaction SHOWCASE-13-TXN-2026-0002
  is_duplicate          : true
  reconciliation_status : duplicate
  Match → (no invoice), confidence 1.0, match_type duplicate

Invoice SHOWCASE-13-INV-2026-0001
  status : paid   ← allocated once, not twice
```

## Key protection

Because Rule 2 fires before Rules 3–10, a duplicate transaction can never accidentally match an invoice — even if its `structured_reference` points to a valid open invoice. The `[RE-IMPORTED]` flag is an absolute override.
