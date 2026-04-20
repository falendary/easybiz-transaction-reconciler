# Showcase 05 — Credit Note Netting

Demonstrates credit note netting: a customer pays the net amount after a credit note is applied, and the engine auto-matches the single bank transaction against both the invoice and the credit note.

## What is credit note netting?

A **credit note** reduces what a customer owes. Instead of paying two separate amounts (full invoice then receiving a refund), the customer pays the net difference in a single transfer.

Example:
- Invoice `SHOWCASE-05-INV-2026-0001` — €585.00 (consulting services)
- Credit note `SHOWCASE-05-CN-2026-0001` — −€100.00 (early-payment discount)
- Customer pays **€485.00** (= 585 − 100) in one bank transfer

## What's in the files

| File | Purpose |
|---|---|
| `invoices.json` | Invoice `SHOWCASE-05-INV-2026-0001` (€585) + credit note `SHOWCASE-05-CN-2026-0001` (−€100) |
| `transactions.json` | Single transaction `SHOWCASE-05-TXN-2026-0001` — €485, description mentions both IDs |

## Why Rule 6 handles this natively

Rule 6 fires when the transaction description contains **multiple invoice/credit-note IDs**.

Steps the engine takes:

| Step | Value |
|---|---|
| Extract IDs from description | `SHOWCASE-05-INV-2026-0001`, `SHOWCASE-05-CN-2026-0001` |
| Look up invoice totals | €585.00 and −€100.00 |
| Sum the totals | 585 + (−100) = **€485.00** |
| Compare to transaction amount | €485.00 = €485.00 ✓ |
| Confidence | **0.95** → `auto_matched` |

The credit note's negative total is just an Invoice record with `type=credit_note` and `total=-100`. Rule 6 sums all found invoices algebraically, so netting happens automatically with no special code path.

## Steps

### Via Django Admin

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard**, filter by `SHOWCASE-05-CUST-001`
6. Observe `SHOWCASE-05-TXN-2026-0001` in the **Reconciled** table (green row)

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/

curl $BASE/transactions/ | python -m json.tool
```

## Expected result

```
Transaction SHOWCASE-05-TXN-2026-0001
  reconciliation_status : auto_matched
  Match → invoice SHOWCASE-05-INV-2026-0001, confidence 0.95, allocated 585.00
  Match → invoice SHOWCASE-05-CN-2026-0001, confidence 0.95, allocated -100.00

Invoice SHOWCASE-05-INV-2026-0001
  status : paid

Invoice SHOWCASE-05-CN-2026-0001
  status : paid   ← credit note fully applied
```
