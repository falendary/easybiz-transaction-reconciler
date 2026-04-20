# EasyBiz Transaction Reconciler

A Django REST API that ingests invoices, bank transactions, and Stripe payout reports, automatically matches them using a rule-based engine, and surfaces unresolved items for manual review via Django Admin.

## What it does

1. **Ingests** three file types:
    - `invoices.json` — invoice and credit note records (upsert on `invoice_id`)
    - `transactions.json` — bank transactions (upsert on `transaction_id`, duplicates flagged)
    - `payout_report.csv` — Stripe payout CSV (PayoutLines linked to parent transactions)

2. **Reconciles** via a 10-rule priority engine:
    - Rule 1 — negative amount or known noise counterparty → `unrelated`
    - Rule 2 — `[RE-IMPORTED]` prefix → `duplicate`
    - Rule 3 — Stripe payout reference → explode PayoutLines, match each charge to invoice
    - Rule 4 — exact `structured_reference` + exact amount → confidence 0.95
    - Rule 5 — exact reference + amount within 2% → confidence 0.85
    - Rule 6 — multiple invoice IDs in description → proportional split (netting-aware)
    - Rule 7 — same reference on multiple transactions → partial payment grouping
    - Rule 8 — fuzzy description + counterparty match → confidence 0.70
    - Rule 9 — AI fallback via Claude API (opt-in, `ENABLE_AI_MATCHING=true`)
    - Rule 10 — no match → `needs_review`, confidence 0.0

   Threshold: ≥ 0.85 → `auto_matched`; < 0.85 → `needs_review`. Locked matches are never overwritten.

3. **Manual review** via Django Admin dashboard (`/admin/reconciler/transaction/dashboard/`) and REST API:
    - Confirm, reject, or mark unrelated per row
    - Upload a file and re-run reconciliation from the same page
    - Filter by date range and customer

4. **Audit trail**: every match change creates paired `AccountEntry` records via Django signals; `ReconciliationRun` records each engine execution.

---

## Stack

- Python 3.11 / Django 4.2 / Django REST Framework
- PostgreSQL 16
- drf-spectacular (Swagger UI at `/api/docs/`)
- Docker Compose for local development

---

## Running locally

### Prerequisites

- Docker + Docker Compose
- Python 3.11 (for running outside Docker)

### With Docker

```bash
cp .env.example .env          # adjust if needed
docker compose up --build
docker compose exec web venv/bin/python manage.py migrate
docker compose exec web venv/bin/python manage.py loaddata currencies sources
docker compose exec web venv/bin/python manage.py createsuperuser
```

App is at `http://localhost:8000`. Admin at `http://localhost:8000/admin/`.

### Without Docker (venv)

```bash
python3.11 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env          # set DB_HOST=localhost
createdb easybiz
venv/bin/python manage.py migrate
venv/bin/python manage.py loaddata currencies sources
venv/bin/python manage.py createsuperuser
venv/bin/python manage.py runserver
```

---

## API quick-start

```bash
BASE=http://localhost:8000/api

# Ingest
curl -X POST $BASE/ingest/invoices/     -F "file=@invoices.json"
curl -X POST $BASE/ingest/transactions/ -F "file=@transactions.json"
curl -X POST $BASE/ingest/payout/       -F "file=@payout_report.csv"

# Reconcile
curl -X POST $BASE/reconcile/

# Review
curl $BASE/transactions/?reconciliation_status=needs_review | python -m json.tool

# Manual actions
curl -X POST $BASE/matches/1/confirm/
curl -X POST $BASE/matches/2/reject/
curl -X POST $BASE/matches/3/mark-unrelated/
```

Full interactive docs: `http://localhost:8000/api/docs/`

---

## Running tests

```bash
venv/bin/python manage.py test reconciler.tests
# or
venv/bin/pytest
```

---

## Resetting data

Drops all ingested/reconciled data while preserving currencies, sources, FX rates, and responsibles:

```bash
venv/bin/python manage.py flush_data          # prompts for confirmation
venv/bin/python manage.py flush_data --yes    # no prompt
```

---

## Showcases

End-to-end scenarios with fixture files and expected results in `showcases/`:

| # | Scenario | Key rule |
|---|---|---|
| 00 | Base reconcile — exact match | Rule 4 |
| 01 | Base reconcile — amount mismatch → needs_review | Rule 10 |
| 02 | One invoice, two partial payments | Rule 7 |
| 03 | One transaction covering two invoices | Rule 6 |
| 04 | Missing transaction uploaded mid-review | Rule 7 (re-run) |
| 05 | Credit note netting — single net payment | Rule 6 |

Each showcase folder contains `invoices.json`, `transactions.json`, and a `README.md` with step-by-step instructions.

---

## What's missing

- **Frontend** — no React UI was built. All review workflows run through Django Admin or the REST API.
- **Authentication** — the API has no auth. All endpoints are open. Django Admin uses session auth only.
- **Multi-tenancy** — data is not partitioned by tenant. Customer isolation is by convention (`customer_id` prefix), not enforced at the DB/auth level.
- **FX rate auto-fetch** — `FXRate` records must be loaded manually; there is no scheduled fetch from an exchange-rate provider.
- **AI matching** (`ENABLE_AI_MATCHING=true`) — implemented but untested end-to-end. Requires a valid `ANTHROPIC_API_KEY`.
- **Pagination** — list endpoints return all records with no pagination limit beyond Django Admin's 200-row cap.
- **Email / webhook notifications** — no alerts when matches need review or reconciliation completes.
- **Audit log for manual actions** — `performed_by` / `performed_at` fields exist on `Match` but are not surfaced in the Admin dashboard.

