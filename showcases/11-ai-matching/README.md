# Showcase 11 — AI Matching (Rule 9)

Demonstrates the Claude AI fallback. The transaction has no structured reference, and the bank counterparty name is a pooled client account with no resemblance to the invoice customer. Every rule-based check fails. Claude reads the description and invoice list, reasons through the context, and identifies the correct match.

## Prerequisites

Enable AI matching before running this showcase:

```env
# .env
ENABLE_AI_MATCHING=true
ANTHROPIC_API_KEY=sk-ant-...
```

Without these, Rule 9 is skipped and the transaction lands in `needs_review` via Rule 10 with `confidence=0.0`.

## What's in the files

| File | Purpose |
|---|---|
| `invoices.json` | Invoice `SHOWCASE-11-INV-2026-0001` — €1,200, customer "SHOWCASE-11 Meridian Law SARL" |
| `transactions.json` | Transaction `SHOWCASE-11-TXN-2026-0001` — €1,200, counterparty "BGL BNP PARIBAS CLIENT ACCT 7721", no reference |

## Why every rule-based rule fails

| Rule | Check | Result |
|---|---|---|
| Rule 1 | Negative amount or noise counterparty | ✗ amount is positive, "BGL BNP PARIBAS" not in noise list |
| Rule 2 | `[RE-IMPORTED]` duplicate flag | ✗ not a duplicate |
| Rule 3 | Stripe payout reference (`po_...`) | ✗ no structured reference |
| Rule 4 | Exact `structured_reference` match | ✗ no structured reference |
| Rule 5 | Reference + amount within 2% | ✗ no structured reference |
| Rule 6 | Multiple invoice IDs in description | ✗ no invoice IDs in description |
| Rule 7 | Partial payment grouping | ✗ no structured reference |
| Rule 8 | Fuzzy counterparty match | ✗ "BGL BNP PARIBAS CLIENT ACCT 7721" similarity to "SHOWCASE-11 Meridian Law SARL" ≈ 0.15, below 0.6 threshold |

Rule 9 fires.

## What Claude receives

```json
{
  "transaction": {
    "id": "SHOWCASE-11-TXN-2026-0001",
    "date": "2026-03-28",
    "amount": "1200.00",
    "currency": "EUR",
    "counterparty": "BGL BNP PARIBAS CLIENT ACCT 7721",
    "structured_reference": null,
    "description": "Q1 legal retainer settlement - Meridian advisory services March 2026"
  },
  "open_invoices": [
    {
      "invoice_id": "SHOWCASE-11-INV-2026-0001",
      "customer": "SHOWCASE-11 Meridian Law SARL",
      "total": "1200.00",
      "currency": "EUR",
      "status": "open"
    }
  ]
}
```

Claude matches on: description mentions "Meridian", invoice customer is "Meridian Law SARL", amounts match exactly, both Q1 2026.

## Steps

### Via Django Admin

1. Set `ENABLE_AI_MATCHING=true` and `ANTHROPIC_API_KEY` in `.env`, restart the server
2. Open `/admin/`
3. **Ingestion Events → Upload Invoices** — upload `invoices.json`
4. **Ingestion Events → Upload Transactions** — upload `transactions.json`
5. **Reconciliation Runs → Run Reconciliation**
6. Open the **Reconciliation Dashboard**, filter by `SHOWCASE-11-CUST-001`
7. Observe the transaction in the **Reconciled** table with match type `exact` and a note starting with `AI:`

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/reconcile/

curl $BASE/matches/?status=auto_matched | python -m json.tool
```

## Expected result (AI enabled)

```
Transaction SHOWCASE-11-TXN-2026-0001
  reconciliation_status : auto_matched  (if confidence ≥ 0.85)
  Match → SHOWCASE-11-INV-2026-0001
  confidence            : 0.90 (Claude's score — may vary)
  note                  : "AI: amount matches exactly, description references Meridian advisory Q1 2026"

Invoice SHOWCASE-11-INV-2026-0001
  status : paid
```

## Expected result (AI disabled)

```
Transaction SHOWCASE-11-TXN-2026-0001
  reconciliation_status : needs_review
  Match → (no invoice), confidence 0.0
  note                  : "No matching invoice found"
```

## Notes on AI confidence

Claude returns a confidence score between 0.0 and 1.0. The engine applies the same threshold as rule-based matching: ≥ 0.85 → `auto_matched`, < 0.85 → `needs_review`. If Claude is uncertain it will return a lower score and the transaction still lands in review — the AI score is not blindly trusted.
