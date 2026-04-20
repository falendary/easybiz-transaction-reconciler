# Showcase 06 — FX Difference

Demonstrates an FX mismatch: the invoice is in EUR but the customer pays in GBP. The engine cannot auto-match because it does not perform currency conversion — the operator must confirm the match manually after verifying the rate.

## What is an FX difference?

When a customer invoiced in EUR pays from a GBP account, their bank converts the amount at the spot rate on the payment date. The wire that arrives in your account is denominated in GBP, not EUR. The economic value is correct, but the numbers don't match without knowing the exchange rate.

Example:
- Invoice `SHOWCASE-06-INV-2026-0001` — **€585.00 EUR**
- EUR/GBP rate on 2026-03-15 — **0.8560**
- Customer sends — **£500.76 GBP** (585 × 0.856)
- Engine sees — £500.76 ≠ €585.00 → no match

## What's in the files

| File | Purpose |
|---|---|
| `invoices.json` | Invoice `SHOWCASE-06-INV-2026-0001` — €585.00 EUR |
| `transactions.json` | Transaction `SHOWCASE-06-TXN-2026-0001` — £500.76 GBP, reference points to the invoice |

## Why the engine lands in needs_review

Rule 4 fires first (exact reference match) but fails the amount check: £500.76 ≠ €585.00.
Rule 5 applies ±2% tolerance but still compares raw numbers without converting currencies: |500.76 − 585| / 585 ≈ 14.4% — far outside tolerance.
Rules 6–8 do not apply. Rule 9 (AI) is off by default.
Rule 10 fires → `needs_review`, confidence 0.0.

## What's missing in the engine

The `FXRate` model exists and rates can be loaded, but no rule currently uses them. A proper FX-aware rule would:

1. Detect that `txn.currency ≠ invoice.currency`
2. Look up the `FXRate` for the pair on `txn.date`
3. Convert `txn.amount` to the invoice currency
4. Re-run the tolerance check on the converted amount

This is deferred — see `DECISIONS.md` → *Partial payments with FX conversion*.

## Steps

### Via Django Admin

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Reconciliation Runs → Run Reconciliation**
5. Open the **Reconciliation Dashboard**, filter by `SHOWCASE-06-CUST-001`
6. Observe `SHOWCASE-06-TXN-2026-0001` in the **Needs Review** table
7. Verify the rate manually (£500.76 ÷ €585.00 ≈ 0.856 on 2026-03-15 is correct)
8. Click **✓ Confirm** to manually accept the match

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/

# Expect needs_review
curl $BASE/transactions/ | python -m json.tool

# Manually confirm after checking the rate
curl -X POST $BASE/matches/1/confirm/
```

## Expected result after reconciliation

```
Transaction SHOWCASE-06-TXN-2026-0001
  currency              : GBP
  amount                : 500.76
  reconciliation_status : needs_review
  Match → invoice SHOWCASE-06-INV-2026-0001, confidence 0.0, match_type needs_review

Invoice SHOWCASE-06-INV-2026-0001
  currency : EUR
  total    : 585.00
  status   : open   ← stays open until match is confirmed
```

## Expected result after manual confirmation

```
Transaction SHOWCASE-06-TXN-2026-0001
  reconciliation_status : confirmed

Invoice SHOWCASE-06-INV-2026-0001
  status : paid
```
