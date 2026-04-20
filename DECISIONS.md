# Architecture & Design Decisions

Tradeoffs made during the build, scope cuts taken deliberately, and accounting edge cases that were deferred and why.

---

## Architecture

### Single Django app (`reconciler/`)

One app holds all 16 models, services, serializers, and views. The alternative — splitting into `invoices`, `transactions`, `matching` apps — would add cross-app import complexity with no benefit at this data volume and team size. Can be split later along the same seams.

### Service layer instead of fat models or fat views

Business logic lives in `*_service.py` modules. Models are pure data; views are pure routing. This makes the reconciliation engine and ingestion logic independently testable without HTTP or ORM fixtures in every test.

### No Celery / async tasks

Reconciliation runs synchronously on `POST /api/reconcile/`. For 80–5 000 transactions this completes in under a second. Celery would add a broker, worker process, and result backend for no practical gain at this scale. If processing time exceeds ~10 s, wrap `run_reconciliation()` in a Celery task and return a run ID — the `ReconciliationRun` model is already designed for it.

### PostgreSQL only, no Redis or search engine

All filtering uses Django ORM. Fuzzy matching in Rule 8 uses Python's `difflib.SequenceMatcher` in-process rather than pg_trgm or Elasticsearch. Acceptable for hundreds of records; not for hundreds of thousands.

---

## Reconciliation engine

### First-match-wins, not scoring all rules

Each transaction is tested against rules in priority order and stops at the first match. This keeps confidence scores interpretable (a score means exactly one rule fired) and avoids the complexity of combining scores across rules. Downside: a transaction that weakly matches Rule 4 and strongly matches Rule 8 will always get Rule 4, even if Rule 8 would be more accurate. Accepted because Rules 1–5 have deterministic criteria, not heuristics.

### Confidence threshold is a hard constant (0.85)

The threshold lives in `CONFIDENCE_THRESHOLD` in `reconciliation_service.py`. It is not per-customer, per-rule, or configurable at runtime. A configurable threshold would need a UI and migration path; the current value was tuned to the showcase dataset and matches accounting intuition (≥85 % confident = auto-accept).

### Rule 7 upgrades to auto_matched when grouped sum equals invoice total

When multiple transactions share the same `structured_reference`, Rule 7 sums all of them. If the sum exactly equals the invoice total it sets confidence to 0.95 (`auto_matched`); otherwise 0.75 (`needs_review`). This means re-uploading a missing transaction and re-running reconciliation automatically resolves the group — no manual confirmation needed.

### Rule 6 handles credit note netting natively

Credit notes are `Invoice` records with `type=credit_note` and a negative `total`. Rule 6 extracts all invoice IDs from the transaction description and sums their totals algebraically. If the sum matches the transaction amount, the match is `auto_matched` at 0.95. No separate netting logic was needed.

### AI fallback (Rule 9) is opt-in and untested end-to-end

`ENABLE_AI_MATCHING=false` by default. The Claude API call is isolated in `claude_service.py` and mocked in all tests. The prompt asks Claude to return a structured JSON match result; if parsing fails or the API errors, the transaction falls through to Rule 10 (`needs_review`). End-to-end validation with a live API key was not performed.

---

## Ingestion

### Upsert on natural keys, never delete

`ingest_invoices` and `ingest_transactions` use `update_or_create` on `invoice_id` / `transaction_id`. Re-uploading the same file is safe and idempotent. Records are never deleted by ingestion — only by the `flush_data` management command. This avoids cascading deletes on `Match` and `AccountEntry` during routine re-imports.

### `[RE-IMPORTED]` prefix convention for duplicate detection

A transaction whose description starts with `[RE-IMPORTED]` has `is_duplicate=True` set on ingestion. Rule 2 then routes it to `duplicate` status. This relies on the upstream bank export naming convention — there is no deduplication based on amount+date+counterparty hash.

### Payout CSV requires transactions to be uploaded first

`ingest_payout` links each `PayoutLine` to its parent `Transaction` via `structured_reference`. If the parent transaction does not exist yet, the PayoutLine is created with `transaction=None` and Rule 3 will not fire for it. The ingestion endpoint returns a count of unlinked lines so the operator knows to upload transactions first.

---

## Accounting edge cases deferred

### Partial payments with FX conversion

Rule 5 accepts amounts within 2% of the invoice total to absorb minor FX rounding. Full FX conversion — looking up the rate on the transaction date and converting to the invoice currency — was not implemented. The `FXRate` model exists and rates can be loaded, but no rule uses them. Deferred because the showcase dataset is EUR-only and the conversion logic would need rate fallback and interpolation.

### VAT / tax-exclusive vs tax-inclusive amounts

Invoices store a single `total` field. Whether that total is tax-inclusive or exclusive is not modelled. A transaction for the net amount will fail Rule 4 if the invoice total includes VAT. Deferred — would require storing `subtotal` and `tax_amount` separately and matching against both values.

### Overpayment and underpayment allocation

If a transaction is €5 over the invoice total, the engine lands in `needs_review` (Rule 5 rejects amounts outside 2% tolerance). There is no rule that auto-creates a separate `needs_review` match for the €5 overpayment remainder. A human must confirm the match and manually note the discrepancy. Proper handling would split the allocated amount and open a second match against a suspense account.

### Contra entries and internal transfers

Two transactions that net to zero (e.g. an outbound and a matching inbound on the same day from the same counterparty) are not detected as a pair. Each is routed independently. If neither is invoiced, both land in `needs_review`. Contra detection would require a second pass over the transaction set after all invoice matches are resolved.

### Refund matching

A Stripe refund arrives as a negative PayoutLine with `type=refund`. Rule 3 creates a match against the original invoice with a negative `allocated_amount`. `recompute_invoice_status` does not subtract refunds from the invoice paid total, so a refunded invoice may incorrectly show `paid`. Deferred — proper refund handling needs a separate refund ledger or a signed allocation model.

### Force-close audit trail

`force_close_invoice` requires a non-empty `note` and sets `force_closed=True` on the Invoice. The note is stored on the invoice but is not visible in the reconciliation dashboard. A full audit trail would append it to an `AuditLog` table with timestamp and user.

---

## Manual review & locking

### `locked_by_user=True` is permanent until explicitly unlocked

Once a human confirms or rejects a match, it is locked and the engine will never overwrite it. Unlocking requires an explicit `POST /api/matches/<id>/unlock/` call. This is intentionally conservative — silent overwrites of human decisions are worse than a slightly awkward unlock flow.

### No optimistic locking / conflict detection

If two users review the same match simultaneously, the second `confirm_match` call will succeed (it is idempotent for already-confirmed matches) or raise a `ValueError` if the match is in an incompatible state. No database-level row locking or ETag-based concurrency control was implemented.

---

## Django Admin dashboard

### Dashboard is on `TransactionAdmin`, not a standalone view

The `/admin/reconciler/transaction/dashboard/` URL is registered via `TransactionAdmin.get_urls()` rather than as a top-level admin view. This keeps the dashboard inside the existing permission model (staff + is_active) without writing a custom `AdminSite`. Tradeoff: the URL is coupled to the `Transaction` model's admin registration.

### 200-row cap per table, no pagination

The dashboard fetches at most 200 `needs_review` and 200 `reconciled` matches. This keeps the page fast without implementing server-side pagination in a custom template. If a customer has more than 200 open items, the user must filter by date range to see them all.

