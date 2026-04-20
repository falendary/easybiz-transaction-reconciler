# Showcase 12 — Full EasyBiz Dataset

The complete production-like dataset: 80 transactions, 50 invoices + 2 credit notes, 1 Stripe payout CSV. Use `output.json` as the reference to verify the app produces the correct reconciliation results.

## Files

| File | Contents |
|---|---|
| `invoices.json` | 50 invoices + 2 credit notes across 8 customers |
| `transactions.json` | 80 transactions (customer payments, Stripe payout, duplicates, noise) |
| `payout_report.csv` | Stripe payout `po_1NfK2r2026EasyBiz` — 5 charges, 1 refund, 1 chargeback |
| `output.json` | Expected reconciliation result for every transaction |

## Upload order

The payout CSV must be uploaded **before** running reconciliation so PayoutLines exist when Rule 3 fires:

1. Upload `invoices.json`
2. Upload `transactions.json`
3. Upload `payout_report.csv`
4. Run reconciliation

## Expected totals

| Status | Count |
|---|---|
| auto_matched | 43 |
| needs_review | 14 |
| duplicate | 5 |
| unrelated | 18 |
| **Total** | **80** |

## What each group exercises

### auto_matched (43)

| TXNs | Rule | Scenario |
|---|---|---|
| TXN-0001 → TXN-0025 | Rule 4 | Exact reference + exact amount |
| TXN-0026, TXN-0027 | Rule 7 | Two partial payments (€1404×2) summing to INV-2026-0026 total €2808 |
| TXN-0028, TXN-0029 | Rule 7 | Same pattern for INV-2026-0027 |
| TXN-0030 | Rule 6 | One payment covering INV-0028+INV-0029+INV-0030 (351+468+585=1404) |
| TXN-0031 | Rule 6 | One payment covering INV-0031+INV-0032+INV-0033 (351+468+585=1404) |
| TXN-0032 | Rule 6 | Credit note netting: INV-0034 2281.50 + CN-0001 -456.30 = 1825.20 |
| TXN-0033 | Rule 6 | Credit note netting: INV-0035 2281.50 + CN-0002 -456.30 = 1825.20 |
| TXN-0034, 0035, 0036 | Rule 5 | FX rounding — within 2% tolerance |
| TXN-0043 (5 of 7 matches) | Rule 3 | Stripe payout charges auto-matched to invoices |

### needs_review (14)

| TXN | Reason |
|---|---|
| TXN-0037 | Description says `INV 20260039` (no dashes) — Rule 8 extracts it, confidence 0.70 |
| TXN-0038 | Description `INV0040/2026` — not parseable by regex; Rule 8 fuzzy-matches Stark counterparty |
| TXN-0039 | French description "facture numéro 41 février" — no ID, Rule 8 fuzzy-matches Pied Piper |
| TXN-0040 | Overpaid by 2.37% (€215.60 vs €210.60) — outside 2% tolerance, Rule 8 finds ID in description |
| TXN-0041 | Overpaid by 2.55% (€215.97 vs €210.60) — same |
| TXN-0042 | Partial payment €361.90 of €374.40 — no second transaction, sum ≠ total |
| TXN-0043 | Mixed payout: 5 auto + refund rf_A1 + chargeback cb_B1 need review |
| TXN-0044 | Advance payment €1500, no reference, no invoice at that amount |
| TXN-0054, 0064, 0074 | Amazon refunds — 'amzn' ≠ 'amazon' noise keyword, no invoice match |
| TXN-0055, 0065, 0075 | VAT refunds from tax authority — no noise keyword, no invoice match |

### duplicate (5)

TXN-0045 through TXN-0049 — all prefixed `[RE-IMPORTED]`, flagged by Rule 2.

### unrelated (18)

TXN-0050 through TXN-0080 (excluding needs_review ones above) — payroll, rent, bank fees, electricity, internal transfers, Slack subscriptions. Classified by Rule 1 (negative amount or known-noise counterparty keyword).

## How to compare with the app

```bash
BASE=http://localhost:8000/api

# Get all matches after reconciliation
curl $BASE/matches/ | python -m json.tool > actual_matches.json

# Get all transactions
curl $BASE/transactions/ | python -m json.tool > actual_transactions.json
```

Check each `transaction_id` in `output.json` against the actual API response:
- `reconciliation_status` on the Transaction
- `status`, `confidence_score`, `match_type`, `invoice` on each Match

## Known gaps in the engine

See `_meta.known_gaps` in `output.json` for the four cases where the current engine produces a sub-optimal result and why.
