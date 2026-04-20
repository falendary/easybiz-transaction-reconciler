# Showcase 02 — One Invoice, Multiple Transactions (Success)

Demonstrates a split payment that the engine resolves automatically: one invoice paid in two instalments whose amounts sum exactly to the invoice total → both transactions `auto_matched`.

## What's in the files

| File | Contents |
|---|---|
| `invoices.json` | Invoice `SHOWCASE-02-INV-2026-0001`, total **€585.00** |
| `transactions.json` | `SHOWCASE-02-TXN-2026-0001` **€300.00** (Feb 10) + `SHOWCASE-02-TXN-2026-0002` **€285.00** (Feb 20) |

300 + 285 = 585 — the split is intentional and exact.

## Why it auto-matches (Rule 7 — grouped partial)

Both transactions reference the same invoice via `structured_reference`. Rule 7 sums **all transactions sharing that reference** and compares against the invoice total:

| Check | Value |
|---|---|
| TXN-0001 amount | €300.00 |
| TXN-0002 amount | €285.00 |
| Combined total | **€585.00** |
| Invoice total | **€585.00** |
| Match | ✓ exact |
| Confidence | **0.95** → `auto_matched` |

If the combined total did not equal the invoice total (e.g. one transaction was missing or had the wrong amount), confidence would drop to 0.75 → `needs_review`.

## Steps

### Via Django Admin

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard**, filter by client `SHOWCASE-02-CUST-001`

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
Transaction SHOWCASE-02-TXN-2026-0001
  reconciliation_status : auto_matched
  Match
    invoice          : SHOWCASE-02-INV-2026-0001
    match_type       : partial
    confidence_score : 0.95
    allocated_amount : 300.00

Transaction SHOWCASE-02-TXN-2026-0002
  reconciliation_status : auto_matched
  Match
    invoice          : SHOWCASE-02-INV-2026-0001
    match_type       : partial
    confidence_score : 0.95
    allocated_amount : 285.00

Invoice SHOWCASE-02-INV-2026-0001
  status : paid   ← 300 + 285 = 585, fully allocated
```
