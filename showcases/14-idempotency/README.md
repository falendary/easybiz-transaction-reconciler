# Showcase 14 — Idempotency

Demonstrates that running reconciliation multiple times on the same data always produces the same result. Re-running never creates duplicate matches, never double-counts invoice payments, and never overwrites manually confirmed decisions.

## What idempotency means here

**Idempotent**: applying the same operation N times has the same effect as applying it once.

For the reconciliation engine this means:
- Run once → 2 matches created
- Run again, no data changed → same 2 matches, no extras
- Re-upload the same files and run again → still the same 2 matches
- Manually confirm a match, then run again → confirmed match is untouched

## What's in the files

| File | Purpose |
|---|---|
| `invoices.json` | Two invoices: `SHOWCASE-14-INV-2026-0001` €585, `SHOWCASE-14-INV-2026-0002` €300 |
| `transactions.json` | Two payments that exactly match each invoice |

## How idempotency is implemented

At the start of `_process_transaction`, the engine deletes all **unlocked** matches for the transaction before creating new ones:

```python
txn.matches.filter(locked_by_user=False).delete()
```

This means:
- Every run starts from a clean slate for unlocked records
- A second run recreates identical matches — net effect is zero change
- Locked matches (`locked_by_user=True`) are never deleted — manual decisions survive

The engine also skips transactions with `locked_by_user=True` at the outer loop level, so the entire transaction is protected once a human has acted on it.

## Steps

### Via Django Admin

**Initial run**

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation** — note the Run ID (e.g. #1)
5. Open the **Reconciliation Dashboard**, filter by `SHOWCASE-14-CUST-001`
6. Both transactions in the Reconciled table; both invoices `paid`

**Run again — nothing changes**

7. **Reconciliation Runs → Run Reconciliation** again (#2)
8. Refresh Dashboard — same result: same 2 matches, same statuses
9. Check **Reconciliation Runs** list — Run #2 shows `total_processed: 2, auto_matched: 2`

**Re-upload same files and run again**

10. Upload `invoices.json` again → `updated: 2` (upsert, no new records)
11. Upload `transactions.json` again → `updated: 2` (upsert, no new records)
12. **Reconciliation Runs → Run Reconciliation** (#3)
13. Dashboard unchanged — still 2 reconciled matches, invoices still `paid`

**Manually confirm a match, then run again**

14. In the Dashboard, click **✓ Confirm** on one match → it becomes `confirmed`, `locked_by_user=True`
15. **Reconciliation Runs → Run Reconciliation** (#4)
16. The confirmed match is untouched — engine skips locked transactions entirely
17. The other auto_matched match is re-evaluated and recreated identically

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"

# Run 1
curl -X POST $BASE/reconcile/
curl $BASE/matches/ | python -m json.tool  # 2 matches, auto_matched

# Run 2 — identical result
curl -X POST $BASE/reconcile/
curl $BASE/matches/ | python -m json.tool  # still 2 matches, no duplicates

# Re-upload same data and run again
curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/
curl $BASE/matches/ | python -m json.tool  # still 2 matches

# Manually confirm one match, then run again
curl -X POST $BASE/matches/1/confirm/
curl -X POST $BASE/reconcile/
curl $BASE/matches/ | python -m json.tool  # match #1 still confirmed, match #2 still auto_matched
```

## Expected result — every run

```
ReconciliationRun
  total_processed  : 2  (locked transactions are excluded from this count)
  auto_matched     : 2
  needs_review     : 0

Transaction SHOWCASE-14-TXN-2026-0001
  reconciliation_status : auto_matched
  Match → SHOWCASE-14-INV-2026-0001, confidence 0.95

Transaction SHOWCASE-14-TXN-2026-0002
  reconciliation_status : auto_matched
  Match → SHOWCASE-14-INV-2026-0002, confidence 0.95

Invoice SHOWCASE-14-INV-2026-0001  status: paid
Invoice SHOWCASE-14-INV-2026-0002  status: paid
```

## What would break idempotency

- If the engine used `create()` instead of delete-then-create, each run would add more Match rows
- If `recompute_invoice_status` summed all matches (including old ones), invoices would appear over-paid after multiple runs
- If locked matches were deleted on re-run, manual confirmations would be lost

All three of these are explicitly guarded against in the implementation.
