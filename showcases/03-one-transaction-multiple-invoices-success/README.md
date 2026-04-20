# Showcase 03 — One Transaction, Multiple Invoices (Success)

Demonstrates a consolidated payment: one bank transfer covering two invoices at once. The engine extracts both invoice IDs from the description, splits the amount proportionally, and auto-matches because the total is exact.

## What's in the files

| File | Contents |
|---|---|
| `invoices.json` | `SHOWCASE-03-INV-2026-0001` **€300.00** + `SHOWCASE-03-INV-2026-0002` **€285.00** |
| `transactions.json` | `SHOWCASE-03-TXN-2026-0001` **€585.00**, description lists both invoice IDs |

300 + 285 = 585 — the single payment exactly covers both invoices.

## Why it auto-matches (Rule 6 — consolidated)

Rule 6 scans the transaction description and structured reference for invoice IDs:

```
"Consolidated payment for SHOWCASE-03-INV-2026-0001 and SHOWCASE-03-INV-2026-0002"
```

| Check | Value |
|---|---|
| IDs extracted | SHOWCASE-03-INV-2026-0001, SHOWCASE-03-INV-2026-0002 |
| Invoices found | 2 |
| Sum of invoice totals | €300 + €285 = **€585** |
| Transaction amount | **€585** |
| Match | ✓ exact |
| Confidence | **0.95** → `auto_matched` |

The amount is split proportionally across the two matches:
- INV-2026-0001 allocated: 585 × (300 / 585) = **€300.00**
- INV-2026-0002 allocated: 585 × (285 / 585) = **€285.00**

If the transaction amount did not equal the invoice sum, confidence would be 0.75 → `needs_review`.

## Steps

### Via Django Admin

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard**, filter by client `SHOWCASE-03-CUST-001`

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/
curl $BASE/matches/ | python -m json.tool
```

## Expected result

```
Transaction SHOWCASE-03-TXN-2026-0001
  reconciliation_status : auto_matched

  Match 1
    invoice          : SHOWCASE-03-INV-2026-0001
    match_type       : consolidated
    confidence_score : 0.95
    allocated_amount : 300.00

  Match 2
    invoice          : SHOWCASE-03-INV-2026-0002
    match_type       : consolidated
    confidence_score : 0.95
    allocated_amount : 285.00

Invoice SHOWCASE-03-INV-2026-0001  →  status : paid
Invoice SHOWCASE-03-INV-2026-0002  →  status : paid
```
