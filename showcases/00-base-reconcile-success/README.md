# Showcase 00 — Base Reconcile Success

Verifies the happy path: one invoice, one matching bank transaction, exact amount and reference → `auto_matched`.

## What's in the files

| File | Contents |
|---|---|
| `invoices.json` | 1 invoice `SHOWCASE-00-INV-2026-0001` for customer `SHOWCASE-00-CUST-001` (SHOWCASE-00 Acme S.à r.l.), total **€585.00** |
| `transactions.json` | 1 bank transaction `SHOWCASE-00-TXN-2026-0001`, amount **€585.00**, `structured_reference = SHOWCASE-00-INV-2026-0001` |

The reconciliation engine will fire **Rule 4 (exact reference + exact amount)** and produce a Match with `confidence = 0.95`, status `auto_matched`.

## Steps

### Via Django Admin

1. Open `/admin/`
2. Go to **Ingestion Events → Upload Invoices** and upload `invoices.json`
3. Go to **Ingestion Events → Upload Transactions** and upload `transactions.json`
4. Go to **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard** (button on the Transactions changelist)

### Via API

```bash
BASE=http://localhost:8000/api

# 1. Upload invoices
curl -X POST $BASE/ingest/invoices/ \
  -F "file=@invoices.json"

# 2. Upload transactions
curl -X POST $BASE/ingest/transactions/ \
  -F "file=@transactions.json"

# 3. Run reconciliation
curl -X POST $BASE/reconcile/

# 4. Inspect the result
curl $BASE/transactions/ | python -m json.tool
curl $BASE/matches/      | python -m json.tool
```

## Expected result

```
Transaction SHOWCASE-00-TXN-2026-0001
  reconciliation_status : auto_matched

Match
  match_type       : exact
  confidence_score : 0.95
  status           : auto_matched
  invoice          : SHOWCASE-00-INV-2026-0001

Invoice SHOWCASE-00-INV-2026-0001
  status : paid
```
