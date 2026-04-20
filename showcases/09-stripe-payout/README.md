# Showcase 09 — Stripe Payout Decomposition

Demonstrates Rule 3: a single Stripe payout transaction is decomposed into individual per-invoice matches using the payout CSV. A refund and a chargeback embedded in the same payout land in `needs_review` because they carry no invoice reference.

## What Stripe payout reconciliation looks like

Stripe settles multiple customer charges into one bank transfer (the "payout"). Your bank statement shows a single line — e.g. €2720.73 from Stripe — with no per-customer breakdown. The payout CSV report contains that breakdown: one row per charge, refund, and chargeback.

The engine matches the bank transaction to the Stripe payout ID, then explodes it into one Match record per PayoutLine row.

## What's in the files

| File | Purpose |
|---|---|
| `invoices.json` | The 5 invoices referenced in the payout CSV (INV-2026-0045 to 0049) |
| `transactions.json` | Single bank transaction — €2720.73, `structured_reference = po_1NfK2r2026EasyBiz` |
| `payout_report.csv` | The real Stripe payout CSV with 5 charges, 1 refund, 1 chargeback |

## The payout CSV in detail

```
charge_id,invoice_id,customer_name,gross_amount,fee,net_amount,type
ch_30NfK,INV-2026-0045,Acme S.à r.l.,526.50,15.52,510.98,charge
ch_31NfK,INV-2026-0046,Globex S.A.,561.60,16.54,545.06,charge
ch_32NfK,INV-2026-0047,Initech Luxembourg SARL,596.70,17.55,579.15,charge
ch_33NfK,INV-2026-0048,Umbrella SCS,631.80,18.57,613.23,charge
ch_34NfK,INV-2026-0049,Hooli SARL-S,666.90,19.59,647.31,charge
rf_A1,,Globex S.A.,-125.00,0.00,-125.00,refund
cb_B1,,Hooli SARL-S,-50.00,0.00,-50.00,chargeback
po_1NfK2r2026EasyBiz,,PAYOUT TOTAL,,,2720.73,payout
```

Net = (510.98 + 545.06 + 579.15 + 613.23 + 647.31) − 125.00 − 50.00 = **€2720.73**

## How Rule 3 processes this

1. Engine sees `structured_reference = po_1NfK2r2026EasyBiz` — matches `^po_` pattern
2. Looks up all `PayoutLine` records linked to this transaction (created during payout CSV upload)
3. For each line:

| Row | Type | Invoice found? | Result |
|---|---|---|---|
| ch_30NfK | charge | INV-2026-0045 ✓ | auto_matched, confidence 0.95, allocated €510.98 |
| ch_31NfK | charge | INV-2026-0046 ✓ | auto_matched, confidence 0.95, allocated €545.06 |
| ch_32NfK | charge | INV-2026-0047 ✓ | auto_matched, confidence 0.95, allocated €579.15 |
| ch_33NfK | charge | INV-2026-0048 ✓ | auto_matched, confidence 0.95, allocated €613.23 |
| ch_34NfK | charge | INV-2026-0049 ✓ | auto_matched, confidence 0.95, allocated €647.31 |
| rf_A1 | refund | no invoice_id | needs_review — "Stripe refund — manual review required" |
| cb_B1 | chargeback | no invoice_id | needs_review — "Stripe chargeback — manual review required" |

Note: allocated amounts are `net_amount` (gross minus Stripe fee), not the invoice total. Stripe keeps the fee.

## Steps

### Via Django Admin

1. Open `/admin/`
2. **Ingestion Events → Upload Invoices** — upload `invoices.json`
3. **Ingestion Events → Upload Transactions** — upload `transactions.json`
4. **Ingestion Events → Upload Payout CSV** — upload `payout_report.csv`
5. **Reconciliation Runs → Run Reconciliation**
6. Open the **Reconciliation Dashboard**
7. Observe:
   - Reconciled table: 5 green rows, one per charge, each linked to its invoice
   - Needs Review table: 2 rows — the refund and the chargeback, with reason "Stripe refund/chargeback — manual review required"

### Via API

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/ingest/payout/       -F "file=@payout_report.csv"
curl -X POST $BASE/reconcile/

curl $BASE/transactions/ | python -m json.tool
curl $BASE/matches/?status=needs_review | python -m json.tool
```

## Expected result

```
Transaction TXN-PAYOUT-2026-0001
  reconciliation_status : needs_review  ← mixed: some auto_matched, some need review

  Match → INV-2026-0045 (Acme),    status auto_matched, allocated €510.98, confidence 0.95
  Match → INV-2026-0046 (Globex),  status auto_matched, allocated €545.06, confidence 0.95
  Match → INV-2026-0047 (Initech), status auto_matched, allocated €579.15, confidence 0.95
  Match → INV-2026-0048 (Umbrella),status auto_matched, allocated €613.23, confidence 0.95
  Match → INV-2026-0049 (Hooli),   status auto_matched, allocated €647.31, confidence 0.95
  Match → (no invoice),            status needs_review, allocated −€125.00 [refund]
  Match → (no invoice),            status needs_review, allocated −€50.00  [chargeback]

Invoice INV-2026-0045 → paid
Invoice INV-2026-0046 → paid
Invoice INV-2026-0047 → paid
Invoice INV-2026-0048 → paid
Invoice INV-2026-0049 → paid
```

The transaction itself stays `needs_review` because not all of its matches are resolved. The refund and chargeback must be manually confirmed or linked to the original invoices they reverse.
