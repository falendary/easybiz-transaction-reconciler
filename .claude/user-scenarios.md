# User Scenarios — EasyBiz Reconciler

This document describes all supported user scenarios, their acceptance criteria,
and edge cases per scenario. Use this as the source of truth for frontend
implementation and backend validation logic.

---

## US-01 — Upload Invoices

**Description**
User uploads `invoices.json` containing invoices and credit notes issued by the SME.

**Steps**
1. User navigates to the Ingest page
2. User selects `invoices.json` from their filesystem
3. User clicks Upload
4. App parses the file and ingests all records
5. App displays a summary of what was created or updated

**Acceptance Criteria**
- File is accepted only if it is valid JSON and contains an array of invoice objects
- Each invoice is upserted on `invoice_id` — re-uploading the same file produces no duplicates
- Credit notes (`type: credit_note`) are ingested correctly alongside invoices
- A summary is shown: how many records were created, updated, and skipped
- An `IngestionEvent` is recorded regardless of success or failure

**Edge Cases**
- Re-uploading the same file → no duplicates, updated count reflects existing records
- File contains a mix of invoices and credit notes → both ingested correctly
- File is malformed JSON → 400 error, clear message, no partial ingestion
- File is empty array → 0 created, warning shown but not an error
- Same `invoice_id` appears twice in one file → second occurrence skipped, warning logged

---

## US-02 — Upload Transactions

**Description**
User uploads `transactions.json` containing bank account movements.

**Steps**
1. User navigates to the Ingest page
2. User selects `transactions.json` from their filesystem
3. User clicks Upload
4. App parses the file, flags duplicates, and ingests all records
5. App displays a summary including how many duplicates were flagged

**Acceptance Criteria**
- Each transaction is upserted on `transaction_id`
- Transactions prefixed with `[RE-IMPORTED]` are flagged as `is_duplicate: true`
- Duplicate transactions are ingested but excluded from reconciliation automatically
- Raw counterparty string is preserved verbatim in `raw_counterparty`
- A `Counterparty` record is created or matched for each unique counterparty name

**Edge Cases**
- Re-uploading the same file → idempotent, no new records
- Transaction with negative amount → ingested normally, will be auto-classified as noise during reconciliation
- Transaction references a payout ID in `structured_reference` → ingested normally, payout lines linked during payout upload
- Counterparty name is garbled (e.g. `INITECHLUXEMBOURGSARL`) → stored as-is, normalization happens during reconciliation
- File contains transactions already matched and locked → ingested without touching existing matches

---

## US-03 — Upload Payout Report

**Description**
User uploads a Stripe payout CSV. The app links each charge line to its parent
transaction and creates `PayoutLine` records for individual matching.

**Steps**
1. User navigates to the Ingest page
2. User selects the payout CSV from their filesystem
3. User clicks Upload
4. App parses the CSV and links lines to their parent transaction via payout ID
5. App displays how many lines were created and which transaction was linked

**Acceptance Criteria**
- App identifies the parent transaction by matching the payout ID in `structured_reference`
- Each row in the CSV creates one `PayoutLine` record
- Re-uploading is idempotent — existing lines are updated, not duplicated
- If no parent transaction is found, ingestion fails with a clear error message

**Edge Cases**
- Parent transaction not yet uploaded → 400 error, message asks user to upload transactions first
- CSV contains refund or chargeback lines → ingested as `type: refund` or `type: chargeback`, flagged for manual review during reconciliation
- Re-uploading payout CSV after reconciliation has run → existing locked matches are not touched
- CSV is malformed or missing required columns → 400 error, no partial ingestion

---

## US-04 — Run Reconciliation

**Description**
User triggers automatic reconciliation. The engine matches transactions to invoices
using rule-based logic and optional AI fallback, assigns confidence scores, and
updates transaction statuses.

**Steps**
1. User clicks the Reconcile button on the Ingest page
2. App runs the reconciliation engine synchronously
3. App displays a run summary: auto-matched, needs review, skipped
4. User is directed to the Review Queue for unresolved items

**Acceptance Criteria**
- All transactions where `locked_by_user: false` are processed
- All transactions where `locked_by_user: true` are skipped without modification
- Each processed transaction receives a `Match` record with a confidence score
- Transactions with confidence >= 0.85 are set to `auto_matched`
- Transactions with confidence < 0.85 are set to `needs_review`
- Noise transactions (negative amount, known counterparty) are auto-classified as `unrelated`
- Duplicate transactions are auto-classified as `duplicate`
- Stripe payout transaction is decomposed via PayoutLines and each charge matched individually
- `Invoice.status` is recomputed after each match
- `AccountEntry` records are created for each match
- A `ReconciliationRun` record is created with summary counts
- Running reconciliation twice produces the same result (idempotent)

**Edge Cases**
- No files uploaded yet → 400 error, clear message
- Reconciliation already running → 409 conflict (prevent concurrent runs)
- AI fallback disabled (`ENABLE_AI_MATCHING=false`) → ambiguous cases go directly to `needs_review`
- Transaction references an invoice not in the system → `needs_review` with note "referenced invoice not found"
- Partial payment detected (two transactions reference same invoice) → both matched as `partial`, invoice set to `partially_paid`
- Consolidated payment (one transaction references multiple invoices in description) → split into multiple Match records, amounts allocated proportionally

---

## US-05 — Review Auto-Matched Results

**Description**
User reviews the results of a reconciliation run — both auto-matched items and
the needs-review queue.

**Steps**
1. User navigates to the Review page
2. User sees two tabs: Auto-Matched and Needs Review
3. User browses matched transactions with their confidence scores and match types
4. User can confirm or reject any auto-matched item

**Acceptance Criteria**
- Auto-Matched tab shows all transactions with `status: auto_matched`, sorted by confidence score ascending (lowest confidence first)
- Needs Review tab shows all transactions with `status: needs_review`
- Each row shows: transaction date, amount, counterparty, description, matched invoice(s), confidence score, match type
- User can confirm an auto-matched item → `status: confirmed`, `locked_by_user: true`
- User can reject an auto-matched item → `status: rejected`, `locked_by_user: true`, transaction returns to Needs Review

**Edge Cases**
- No reconciliation has been run yet → empty state with prompt to run reconciliation
- All items are auto-matched with high confidence → Needs Review tab is empty
- User rejects a match → transaction reappears in Needs Review tab immediately
- User confirms a match → item moves out of Auto-Matched tab immediately

---

## US-06 — Manually Resolve a Transaction

**Description**
User manually links a transaction in the review queue to one or more invoices.

**Steps**
1. User finds a transaction in the Needs Review tab
2. User clicks Resolve
3. User selects one or more invoices from a dropdown of open invoices
4. User enters allocated amounts per invoice
5. User adds an optional note
6. User confirms — match is saved and transaction is locked

**Acceptance Criteria**
- Dropdown shows only invoices with `status: open` or `partially_paid`
- Allocated amounts must sum exactly to the transaction total before saving
- Saving creates one `Match` record per invoice with `status: manually_matched` and `locked_by_user: true`
- `Invoice.status` is recomputed after saving
- `AccountEntry` records are created for the new matches
- Transaction moves out of the Needs Review tab immediately

**Edge Cases**
- User selects one invoice but enters wrong amount → validation error before saving
- User allocates to multiple invoices and amounts don't sum to transaction total → validation error, save blocked
- User resolves a transaction that was already auto-matched → only possible after rejecting the existing match first
- Selected invoice becomes paid by another transaction before user saves → conflict error, user asked to refresh

---

## US-07 — Mark Transaction as Unrelated

**Description**
User marks a transaction as noise — salary, rent, bank fees, or any movement
unrelated to invoices.

**Steps**
1. User finds a transaction in the Needs Review tab
2. User clicks Mark as Unrelated
3. User enters a mandatory note explaining why
4. User confirms

**Acceptance Criteria**
- Note is mandatory — save is blocked without it
- Transaction `status` set to `unrelated`, `locked_by_user: true`
- Transaction disappears from Needs Review tab immediately
- No `Invoice.status` change triggered

**Edge Cases**
- User marks a positive-amount transaction as unrelated → allowed, note is mandatory
- User tries to mark an already-confirmed match as unrelated → blocked — must unlock first
- Auto-classified noise transaction (salary) appears in Needs Review after re-run → should not happen — noise is auto-classified at confidence 1.0 and locked

---

## US-08 — Force-Close a Partially Paid Invoice

**Description**
User closes an invoice that has received partial payment and will not receive
the remainder — for example, after a write-off agreement with the client.

**Steps**
1. User navigates to the invoice detail page
2. User sees the outstanding balance and existing partial matches
3. User clicks Force Close
4. User enters a mandatory note
5. User confirms

**Acceptance Criteria**
- Force Close is only available on invoices with `status: partially_paid`
- Note is mandatory — save is blocked without it
- Invoice `status` set to `force_closed`
- All linked matches set to `locked_by_user: true`
- `AccountEntry` records are not modified — the partial payment history is preserved

**Edge Cases**
- User tries to force-close a fully paid invoice → button not shown, not available via API
- User tries to force-close an invoice with no payments at all → allowed, note required
- Force-closed invoice is referenced by a new transaction after the fact → new transaction goes to `needs_review` with note "invoice already force-closed"

---

## US-09 — Unlock and Re-Resolve a Match

**Description**
User discovers that a previously confirmed or manually assigned match was wrong
and needs to correct it.

**Steps**
1. User finds the match in the Reconciled tab or invoice detail
2. User clicks Unlock
3. User enters a mandatory note explaining why
4. Match is unlocked — transaction returns to Needs Review
5. User re-resolves via US-06

**Acceptance Criteria**
- Unlock sets `locked_by_user: false` on the match
- Transaction `reconciliation_status` returns to `needs_review`
- `Invoice.status` is recomputed — may return to `open` or `partially_paid`
- `AccountEntry` records from the original match are reversed
- Unlock action is logged with the user note for audit

**Edge Cases**
- User unlocks a match on a force-closed invoice → force-close status is also cleared, invoice returns to `partially_paid` or `open`
- User unlocks one of multiple matches on a consolidated payment → only that match is unlocked, others remain locked
- User unlocks and does not re-resolve → transaction stays in Needs Review indefinitely, which is valid

---

## US-10 — View Reconciliation Health

**Description**
User checks the overall reconciliation status — how many invoices are open,
how many transactions are unresolved, and whether the books balance to zero.

**Steps**
1. User navigates to the Dashboard
2. User sees summary metrics per customer and overall

**Acceptance Criteria**
- Dashboard shows: total invoices, open / partially_paid / paid / force_closed counts
- Dashboard shows: total transactions, reconciled / needs_review / unrelated / duplicate counts
- Per-customer reconciliation balance shown (`receivable + bank = 0` check)
- Last reconciliation run timestamp and summary visible

**Edge Cases**
- No reconciliation run yet → balance shown as 0, metrics show raw ingested counts
- Balance is non-zero → highlighted visually as unresolved remainder
- Multiple reconciliation runs → dashboard reflects current state, not last run only

---

## Out of Scope User Scenarios

The following scenarios are explicitly not supported in this implementation:

| Scenario | Reason |
|---|---|
| Link a prepayment to a future invoice | No invoice exists at match time — deferred |
| Resolve a Stripe refund or chargeback | No invoice reference available — manual note only |
| Export reconciliation results to CSV | Out of scope for this delivery |
| Multi-user concurrent review | No authentication or locking beyond `locked_by_user` |
| Undo a force-close without unlocking | Covered by US-09 unlock flow |
| Create or edit invoices manually | Invoices are ingestion-only in this version |
| Create or edit transactions manually | Transactions are ingestion-only in this version |
