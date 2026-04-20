# Showcase 04 — Manual Upload of Missing Transaction

Demonstrates the correction flow: the bank export is incomplete (only one of two instalments arrived), reconciliation flags it for review, the user uploads the missing transaction, re-runs reconciliation, and everything auto-matches.

## What's in the files

| File | Purpose |
|---|---|
| `invoices.json` | Invoice `SHOWCASE-04-INV-2026-0001`, total **€585.00** |
| `transactions.json` | First instalment only — `SHOWCASE-04-TXN-2026-0001` **€300.00** |
| `fix_transactions.json` | Missing second instalment — `SHOWCASE-04-TXN-2026-0002` **€285.00** |

## Why the first run lands in needs_review

Rule 7 fires for `TXN-2026-0001` (€300 < €585). It sums **all transactions referencing this invoice**:

| Transactions referencing SHOWCASE-04-INV-2026-0001 | Amount |
|---|---|
| SHOWCASE-04-TXN-2026-0001 | €300.00 |
| **Total** | **€300.00** ≠ €585.00 |

Sum does not equal invoice total → confidence **0.75** → `needs_review`.

## Why the second run auto-matches

After uploading `fix_transactions.json`, both transactions reference the same invoice. Rule 7 re-sums:

| Transactions referencing SHOWCASE-04-INV-2026-0001 | Amount |
|---|---|
| SHOWCASE-04-TXN-2026-0001 | €300.00 |
| SHOWCASE-04-TXN-2026-0002 | €285.00 |
| **Total** | **€585.00** = €585.00 ✓ |

Sum equals invoice total → confidence **0.95** → `auto_matched` for both.

Reconciliation is idempotent — re-running it replaces the old `needs_review` matches with the new `auto_matched` ones.

## Steps

### Via Django Admin

**Round 1 — incomplete data**

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard**, filter by `SHOWCASE-04-CUST-001`
6. Observe `SHOWCASE-04-TXN-2026-0001` in the **Needs Review** table

**Round 2 — upload the missing transaction and re-reconcile**

7. **Ingestion Events → Upload Transactions** — upload `fix_transactions.json`
8. **Reconciliation Runs → Run Reconciliation** ← re-run is safe, results replace previous
9. Refresh the Dashboard — both transactions now appear in the **Reconciled** table

### Via API

```bash
BASE=http://localhost:8000/api

# Round 1
curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/

# Inspect — expect needs_review
curl $BASE/transactions/ | python -m json.tool

# Round 2
curl -X POST $BASE/ingest/transactions/ -F "file=@fix_transactions.json"
curl -X POST $BASE/reconcile/

# Inspect — expect auto_matched
curl $BASE/transactions/ | python -m json.tool
```

## Expected result after Round 1

```
Transaction SHOWCASE-04-TXN-2026-0001
  reconciliation_status : needs_review
  Match → invoice SHOWCASE-04-INV-2026-0001, confidence 0.75

Invoice SHOWCASE-04-INV-2026-0001
  status : open
```

## Expected result after Round 2

```
Transaction SHOWCASE-04-TXN-2026-0001
  reconciliation_status : auto_matched
  Match → invoice SHOWCASE-04-INV-2026-0001, confidence 0.95, allocated 300.00

Transaction SHOWCASE-04-TXN-2026-0002
  reconciliation_status : auto_matched
  Match → invoice SHOWCASE-04-INV-2026-0001, confidence 0.95, allocated 285.00

Invoice SHOWCASE-04-INV-2026-0001
  status : paid   ← 300 + 285 = 585
```
