# Showcase 01 — Base Reconcile Fail (Amount Mismatch)

Demonstrates a mismatch: the transaction references the correct invoice but the amount is wrong. No rule produces a confident match — the transaction lands in `needs_review` with no invoice linked.

## What's in the files

| File | Contents |
|---|---|
| `invoices.json` | Invoice `SHOWCASE-01-INV-2026-0001`, total **€585.00** |
| `transactions.json` | Transaction `SHOWCASE-01-TXN-2026-0001`, amount **€650.00**, `structured_reference = SHOWCASE-01-INV-2026-0001` |

## Why every rule fails

| Rule | Condition | Result |
|---|---|---|
| Rule 4 — Exact | amount €650 ≠ invoice €585 | ✗ skip |
| Rule 5 — FX tolerance | diff = 11.1 %, tolerance is 2 % | ✗ skip |
| Rule 7 — Partial payment | only fires when amount < invoice total; 650 > 585 | ✗ skip |
| Rule 8 — Fuzzy | counterparty fuzzy + amount tolerance check also fails (11 % diff) | ✗ skip |
| Rule 10 — No match | fallback | → `needs_review`, confidence 0.0, no invoice |

## Steps

### Via Django Admin

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard** and filter by client `SHOWCASE-01-CUST-001`

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/
curl "$BASE/matches/?transaction__transaction_id=SHOWCASE-01-TXN-2026-0001" | python -m json.tool
```

## Expected result

```
Transaction SHOWCASE-01-TXN-2026-0001
  reconciliation_status : needs_review

Match
  match_type       : exact
  confidence_score : 0.0
  status           : needs_review
  invoice          : null

Invoice SHOWCASE-01-INV-2026-0001
  status : open   ← unpaid, no confirmed match
```

The transaction appears in the **Needs Review** table in the Dashboard. Use Confirm / Reject / Unrelated buttons to resolve it manually.
