# Implementation Plan

---

## Issue 1 — Create Django Base Project

**Description**

Scaffold the Django project with PostgreSQL, Django REST Framework, and drf-spectacular. Configure environment variables via `.env`. Set up `docker-compose.yml` so the entire stack (Django + PostgreSQL) runs with a single `docker compose up` command.

**Definition of Done**
- `docker compose up` starts Django and PostgreSQL with no errors
- Django admin is accessible at `/admin/`
- `/api/docs/` serves Swagger UI via drf-spectacular
- `.env.example` documents all required environment variables
- `README.md` contains one-command setup instructions

**Out of Scope**
- SSL, CORS, CSRF configuration
- Authentication beyond Django defaults
- Frontend setup (covered in a separate issue)

---

## Issue 2 — Create Models and Django Admin

**Description**

Define the core data models and register them in Django Admin for debugging and manual inspection.

Models:
- `Customer` — name, customer_id, VAT number
- `Invoice` — id, type (invoice / credit_note), customer FK, issue_date, due_date, currency, subtotal, tax_total, total, status (open / partially_paid / paid / force_closed)
- `InvoiceLineItem` — invoice FK, description, quantity, unit_price, tax_rate, amount
- `Transaction` — id, date, amount, currency, counterparty_name, structured_reference, description, is_duplicate
- `PayoutLine` — transaction FK, charge_id, invoice_id, customer_name, gross_amount, fee, net_amount, type (charge / refund / chargeback)
- `Match` — transaction FK, invoice FK, allocated_amount, confidence_score, match_type, status, locked_by_user, note, created_at, updated_at

Match status values: `auto_matched`, `needs_review`, `confirmed`, `manually_matched`, `rejected`, `unrelated`

Match type values: `exact`, `partial`, `consolidated`, `fx`, `credit_note`, `payout`, `prepayment`, `duplicate`, `noise`

**Definition of Done**
- All models have migrations and apply cleanly
- All models are registered in Django Admin with useful list display fields
- `DecimalField` used for all monetary values
- `Match.locked_by_user` prevents auto-reconciliation from overwriting human decisions

**Out of Scope**
- Multi-tenancy — single SME context only
- Soft delete or versioning
- Any model beyond the listed entities

---

## Issue 3 — Create API Endpoints and Serializers

**Description**

Expose read endpoints for the core entities so the frontend can display current state.

Endpoints:
- `GET /api/invoices/` — list all invoices with status
- `GET /api/invoices/<id>/` — detail with line items and linked matches
- `GET /api/transactions/` — list all transactions
- `GET /api/transactions/<id>/` — detail with linked matches
- `GET /api/matches/` — list all matches, filterable by status

**Definition of Done**
- All endpoints return correct serialized data
- Matches endpoint supports `?status=needs_review` filter
- All endpoints documented in Swagger UI
- Basic unit tests cover each endpoint (200 response, correct fields)

**Out of Scope**
- Pagination (dataset is small)
- Write operations via these endpoints (covered in later issues)
- Authentication or permissions

---

## Issue 4 — Create API Endpoints for File Uploads

**Description**

Allow users to upload the three source files. Ingestion must be idempotent — re-uploading the same file produces no duplicates.

Endpoints:
- `POST /api/ingest/invoices/` — accepts `invoices.json`, upserts on `id`, handles `type: credit_note`
- `POST /api/ingest/transactions/` — accepts `transactions.json`, upserts on `id`, detects `[RE-IMPORTED]` prefix and flags `is_duplicate`
- `POST /api/ingest/payout/` — accepts `.csv`, upserts `PayoutLine` records linked to their parent transaction by payout reference

**Definition of Done**
- All three endpoints accept file upload and parse correctly
- Re-uploading the same file twice produces identical database state (no duplicates)
- Credit notes ingested correctly as `type: credit_note`
- Duplicate transactions flagged with `is_duplicate: true`
- Unit tests cover happy path and re-upload idempotency for each endpoint

**Out of Scope**
- Cloud file storage — files are processed in memory and not persisted to disk
- File format validation beyond minimum required fields
- Support for formats other than the provided samples

---

## Issue 5 — Create API Endpoint for Reconciliation

**Description**

Implement the reconciliation engine and expose it as a single endpoint. Rules fire in priority order. Matches with `locked_by_user: true` are never touched.

`POST /api/reconcile/`

Rule priority:
1. Negative amount or known noise counterparty → `unrelated`, confidence 1.0
2. `is_duplicate: true` → `duplicate`, confidence 1.0
3. Payout reference detected → explode via PayoutLines, match each charge to its `invoice_id`
4. `structured_reference` exact match + amount exact → confidence 0.95
5. `structured_reference` exact + amount within 2% tolerance → confidence 0.85 (FX / rounding)
6. Multiple invoice IDs detected in description → consolidated split
7. Same reference on multiple transactions → partial payment grouping
8. Description fuzzy-matches invoice ID + counterparty fuzzy-matches customer name → confidence 0.70
9. AI fallback for ambiguous cases (optional, controlled by `ENABLE_AI_MATCHING` env variable)
10. No match found → `needs_review`, confidence 0.0

Matches above 0.85 confidence are set to `auto_matched`. Below 0.85 go to `needs_review`.

**Definition of Done**
- Endpoint is idempotent — running twice produces the same result
- `locked_by_user: true` matches are never modified
- All 80 transactions produce a Match record after reconciliation
- Invoice status updated after each match (`open` → `partially_paid` → `paid`)
- Unit tests cover each rule with a representative fixture
- AI fallback is disabled by default and activates only when `ENABLE_AI_MATCHING=true`

**Out of Scope**
- Async/background processing — runs synchronously
- Real-time FX rate lookup — fixed tolerance used instead
- Prepayment auto-resolution — TXN-0044 deferred to review queue
- Stripe refund and chargeback auto-resolution — deferred to review queue

---

## Issue 6 — Create API Endpoints for Manual Intervention

**Description**

Allow reviewers to resolve items in the `needs_review` queue. All manual actions set `locked_by_user: true` and append a note to the audit trail.

Endpoints:
- `POST /api/matches/` — create a manual match between a transaction and one or more invoices, with allocated amounts
- `PATCH /api/matches/<id>/` — update match status (`confirmed`, `rejected`, `unrelated`) and add a note
- `DELETE /api/matches/<id>/` — remove a match and unlock the transaction (sets `locked_by_user: false`, returns to `needs_review`)
- `POST /api/invoices/<id>/force-close/` — force-close a partially paid invoice regardless of outstanding amount; requires a mandatory note

**Definition of Done**
- All manual actions set `locked_by_user: true`
- Force-close requires a non-empty note
- Deleted matches return the transaction to `needs_review` and unlock it
- Invoice status recalculated after every match change
- Unit tests cover: manual match creation, confirmation, rejection, force-close, and unlock flow

**Out of Scope**
- Bulk actions
- Match history / event sourcing — only current state is stored
- Frontend UI (covered in a separate issue)

---

## Issue 7 — Create React Frontend

**Description**

Build a minimal, functional React frontend that covers the core user journey.

Pages:
- **Ingest page** — three file upload inputs (invoices, transactions, payout report) with upload status per file and a **Reconcile** button
- **Review queue** — table of transactions with `status: needs_review`, showing amount, date, counterparty, description, and candidate invoices. Actions: link to invoice, split across invoices, mark as unrelated
- **Reconciled tab** — read-only list of confirmed matches with confidence score and match type

**Definition of Done**
- User can upload all three files and trigger reconciliation from the UI
- Review queue shows all unresolved transactions
- User can resolve any item in the queue without leaving the page
- Confirmed matches visible in the reconciled tab
- No end-to-end tests required — manual smoke test is sufficient

**Out of Scope**
- Polished visual design
- Drag-and-drop interactions
- Mobile responsiveness
- End-to-end or integration tests
