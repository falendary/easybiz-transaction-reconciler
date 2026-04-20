# Data Models — EasyBiz Reconciler

This document describes the complete data model for the EasyBiz Invoice ↔ Transaction Reconciler.
Use this as the source of truth when generating Django models, migrations, serializers, and admin configuration.

---

## Context

Single-repository Django + PostgreSQL + React app.
Scoped to a single SME client context — no multi-tenancy.
All monetary values use `DecimalField(max_digits=12, decimal_places=2)`.
All currency fields are FK to `Currency` — never a raw CharField.
`Invoice.status` is always recomputed from Match records — never set directly.
`AccountEntry` records are created automatically via Django signals on Match save — never manually.
`Responsible` extends Django's built-in `User` via OneToOneField — authentication is handled by Django auth.
`Source` is a reference table seeded from a fixture — adding a new integration requires a data migration, not a code change.

---

## Models

### `Currency`
ISO 4217 currency reference table. Seeded via fixture on first migration.

```
code               CharField(max_length=3, unique=True)   # EUR, USD, GBP
name               CharField                               # Euro, US Dollar
symbol             CharField(max_length=5)                 # €, $, £
decimal_places     PositiveSmallIntegerField               # 2 for most, 0 for JPY
is_active          BooleanField(default=True)
created_at         DateTimeField(auto_now_add=True)
```

---

### `Source`
Origin system that produced the data. Seeded via fixture on first migration.
Determines which parser is used during ingestion and provides traceability per record.

```
name            CharField(unique=True)   # "Stripe", "Demo CRM", "ING Bank"
source_type     CharField                # choices: bank | payment_processor | crm | erp | manual
description     TextField(null=True)
is_active       BooleanField(default=True)
created_at      DateTimeField(auto_now_add=True)
```

Seed values:
```
name="Stripe"      source_type="payment_processor"
name="Demo CRM"    source_type="crm"
name="ING Bank"    source_type="bank"
```

---

### `Responsible`
Profile extension for Django's built-in User model.
Tracks who performed manual reconciliation actions.
System-generated matches have no responsible — only human actions carry one.

```
user            OneToOneField(django.contrib.auth.User)
display_name    CharField    # "Marie Lambert"
role            CharField    # choices: reviewer | admin
created_at      DateTimeField(auto_now_add=True)
```

Used on:
```
Match.performed_by          FK to Responsible, null=True  (null = system action)
Match.performed_at          DateTimeField, null=True
Invoice.force_closed_by     FK to Responsible, null=True
Invoice.force_closed_at     DateTimeField, null=True
```

---

### `IngestionEvent`
Records every file upload. Stores raw content for reprocessing and audit.
Links to the Source that produced the file.

```
file_type          CharField  # choices: invoices | transactions | payout
filename           CharField
uploaded_at        DateTimeField(auto_now_add=True)
raw_content        TextField  # original file content verbatim
status             CharField  # choices: pending | success | failed
error_message      TextField(null=True, blank=True)
source             ForeignKey(Source)
```

---

### `Customer`
A billing client of the SME. Parsed from invoices.json on ingestion.

```
customer_id        CharField(unique=True)   # CUST-001
name               CharField                # Acme S.à r.l.
vat_number         CharField(null=True)     # LU12345678
address            TextField(null=True)
created_at         DateTimeField(auto_now_add=True)
```

---

### `Account`
Represents one side of the double-entry ledger per customer.
One receivable account and one bank account per customer.
Stripe payout transactions additionally use a stripe_clearing account.

```
customer           ForeignKey(Customer)
account_type       CharField  # choices: receivable | bank | stripe_clearing
currency           ForeignKey(Currency)
name               CharField  # "Accounts Receivable — Acme S.à r.l."
created_at         DateTimeField(auto_now_add=True)
```

Reconciliation check:
```python
# Should equal 0 when fully reconciled for a given customer
receivable_balance + bank_balance == 0
```

---

### `Counterparty`
Normalized bank counterparty names. Built during transaction ingestion.
Links raw bank names to known Customers where possible.

```
raw_name           CharField   # "INITECHLUXEMBOURGSARL" — exactly as arrived
normalized_name    CharField   # "Initech Luxembourg SARL" — cleaned
customer           ForeignKey(Customer, null=True)  # linked if matched
description        TextField(null=True)  # "Stripe payment processor"
created_at         DateTimeField(auto_now_add=True)
```

---

### `FXRate`
Exchange rate for a specific date. Seeded with fixed demo rates.
In production, replace source="fixed_demo" with source="ECB" and fetch live rates.

```
base_currency      ForeignKey(Currency, related_name='fx_base')
quote_currency     ForeignKey(Currency, related_name='fx_quote')
rate               DecimalField
date               DateField
source             CharField  # choices: fixed_demo | ECB
created_at         DateTimeField(auto_now_add=True)

unique_together: (base_currency, quote_currency, date)
```

---

### `Invoice`
An invoice or credit note issued by the SME to a customer.
`status` is always derived — recomputed from confirmed Match records, never set directly.
`force_close_note` is mandatory when status is force_closed.

```
invoice_id         CharField(unique=True)   # INV-2026-0001
type               CharField  # choices: invoice | credit_note
customer           ForeignKey(Customer)
issue_date         DateField
due_date           DateField
currency           ForeignKey(Currency)
subtotal           DecimalField
tax_total          DecimalField
total              DecimalField
status             CharField  # choices: open | partially_paid | paid | force_closed
force_close_note   TextField(null=True, blank=True)
force_closed_by    ForeignKey(Responsible, null=True)
force_closed_at    DateTimeField(null=True)
source             ForeignKey(Source, null=True)   # derived from IngestionEvent
ingestion_event    ForeignKey(IngestionEvent)
created_at         DateTimeField(auto_now_add=True)
```

Status transition logic:
```python
def recompute_status(invoice):
    allocated = Match.objects.filter(
        invoice=invoice,
        status__in=['auto_matched', 'confirmed', 'manually_matched']
    ).aggregate(Sum('allocated_amount'))['allocated_amount__sum'] or 0

    if allocated == 0:
        return 'open'
    elif allocated >= invoice.total:
        return 'paid'
    else:
        return 'partially_paid'
    # force_closed is only set explicitly by a human action
```

---

### `InvoiceLineItem`
Individual line items belonging to an invoice.

```
invoice            ForeignKey(Invoice, related_name='line_items')
line_id            CharField   # INV-2026-0001-L1
description        CharField
quantity           DecimalField
unit_price         DecimalField
tax_rate           DecimalField
amount             DecimalField
```

---

### `Transaction`
A single bank account movement. Imported from transactions.json.
`reconciliation_status` is the operational field for the review queue.
`locked_by_user` is the protection gate — reconciliation engine never touches locked records.

```
transaction_id         CharField(unique=True)   # TXN-0001
date                   DateField
amount                 DecimalField             # negative = outgoing
currency               ForeignKey(Currency)
counterparty           ForeignKey(Counterparty, null=True)
raw_counterparty       CharField                # raw string preserved as arrived
structured_reference   CharField(null=True)
description            TextField(null=True)
is_duplicate           BooleanField(default=False)
reconciliation_status  CharField  # choices: unprocessed | auto_matched | needs_review | reconciled | unrelated | duplicate
locked_by_user         BooleanField(default=False)
source                 ForeignKey(Source, null=True)   # derived from IngestionEvent
ingestion_event        ForeignKey(IngestionEvent)
created_at             DateTimeField(auto_now_add=True)
```

---

### `PayoutLine`
Individual charge lines extracted from a Stripe payout CSV.
Each PayoutLine belongs to the single Stripe Transaction in transactions.json.
Refund and chargeback lines have no invoice reference and go to needs_review.

```
transaction        ForeignKey(Transaction)   # the Stripe TXN-0043
charge_id          CharField                 # ch_30NfK
raw_invoice_id     CharField(null=True)      # raw invoice reference from CSV
customer_name      CharField                 # as arrived in CSV
gross_amount       DecimalField
fee                DecimalField
net_amount         DecimalField
type               CharField  # choices: charge | refund | chargeback
ingestion_event    ForeignKey(IngestionEvent)
```

---

### `Match`
The reconciliation fact — one allocation line between one Transaction and one Invoice.
Multiple Match records form complex relationships (partial payments, consolidated splits).

Integrity rule:
```
SUM(Match.allocated_amount WHERE transaction=X AND status IN active_statuses)
    == Transaction.amount
```

`locked_by_user` is set to True on any human action — confirmed, manually_matched, rejected, unrelated.
Reconciliation engine skips all records where locked_by_user=True.

```
transaction        ForeignKey(Transaction)
invoice            ForeignKey(Invoice)
payout_line        ForeignKey(PayoutLine, null=True)
allocated_amount   DecimalField
confidence_score   DecimalField   # 0.00 – 1.00
match_type         CharField      # choices: exact | partial | consolidated | fx | credit_note | payout | noise | duplicate | prepayment
status             CharField      # choices: auto_matched | needs_review | confirmed | manually_matched | rejected | unrelated
locked_by_user     BooleanField(default=False)
performed_by       ForeignKey(Responsible, null=True)   # null = system action
performed_at       DateTimeField(null=True)
note               TextField(null=True, blank=True)
created_at         DateTimeField(auto_now_add=True)
updated_at         DateTimeField(auto_now=True)
```

Confidence thresholds:
```
>= 0.85  →  auto_matched
<  0.85  →  needs_review
```

---

### `AccountEntry`
Double-entry bookkeeping ledger line.
Created automatically via Django signal on Match save — never created manually.
Every Match produces exactly two AccountEntry rows (receivable + bank).

```
account            ForeignKey(Account)
match              ForeignKey(Match, null=True)
invoice            ForeignKey(Invoice, null=True)
transaction        ForeignKey(Transaction, null=True)
amount             DecimalField   # positive or negative
entry_type         CharField      # choices: debit | credit
created_at         DateTimeField(auto_now_add=True)
```

Reconciliation health check:
```python
def reconciliation_balance(customer):
    receivable = AccountEntry.objects.filter(
        account__customer=customer,
        account__account_type='receivable'
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    bank = AccountEntry.objects.filter(
        account__customer=customer,
        account__account_type='bank'
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    return receivable + bank  # 0 = fully reconciled
```

---

### `ReconciliationRun`
Records each reconciliation run for audit and debugging.
Summary counts are computed at the end of each run.

```
started_at              DateTimeField(auto_now_add=True)
finished_at             DateTimeField(null=True)
status                  CharField  # choices: running | completed | failed
total_processed         PositiveIntegerField(default=0)
auto_matched_count      PositiveIntegerField(default=0)
needs_review_count      PositiveIntegerField(default=0)
skipped_locked_count    PositiveIntegerField(default=0)
error_message           TextField(null=True, blank=True)
```

---

## Relationship Map

```
Currency  ←──────────────────────────────────────────────┐
                                                          │ (all currency fields)
Source    ←── IngestionEvent ←── Invoice ──→ Customer ──→ Account
                                    │           │
                             InvoiceLineItem    └──→ Counterparty
                                    │
                             force_closed_by ──→ Responsible ←── django.auth.User
                                                      ↑
Source    ←── IngestionEvent ←── Transaction ──→ Counterparty
                                    │
                                PayoutLine
                                    │
                                  Match ──→ performed_by ──→ Responsible
                                    │
                             AccountEntry ──→ Account
                                    ↑
                          ReconciliationRun

FXRate ──→ Currency (base + quote)
```

---

## Key Business Rules

1. `Invoice.status` is never set directly — always recomputed via `recompute_status()`
2. `Match.locked_by_user = True` — reconciliation engine never modifies these records
3. `AccountEntry` records are created via Django signal on Match save, deleted on Match delete
4. Re-ingesting any file is safe — all ingestion endpoints upsert on natural id
5. Confidence >= 0.85 → `auto_matched`, below → `needs_review`
6. Every Transaction must eventually have its `allocated_amount` fully accounted for across its Match records
7. `force_close_note` is mandatory when an invoice is force-closed by a human
8. Stripe payout lines of type `refund` or `chargeback` always go to `needs_review` — never auto-matched
9. `Match.performed_by` and `Invoice.force_closed_by` are null for system actions — only human actions carry a Responsible
10. `Invoice.source` and `Transaction.source` are derived from their `IngestionEvent.source` on ingestion — never set independently
11. `Source` and `Currency` are reference tables — adding new values requires a data migration, not a code change
12. `Responsible` is always linked to a Django auth `User` — no orphan Responsible records
