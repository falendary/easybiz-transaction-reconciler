# Showcase 10 — Valid Structure, Garbage Data

Demonstrates the difference between errors the service catches and errors it silently accepts. All files are valid JSON with all required fields present — the problems are in the values.

## Two categories of garbage

### Category A — hard crash (batch rolled back)

The service fails loudly. The entire batch is rolled back, an `IngestionEvent` with `status=failed` is written, and a 400 error is returned.

### Category B — silent acceptance (ingested, reconciliation misbehaves)

The service accepts the record without complaint. No error is raised. The garbage lands in the database and produces wrong or unpredictable reconciliation results.

---

## Files

### `invoices_bad_amount.json` — Category A

```json
"total": "€585,00"
```

European-formatted number with currency symbol. The `_dec()` helper calls `Decimal("€585,00")` which raises `InvalidOperation`. **Entire batch fails.**

```
Error: InvalidOperation [<class 'decimal.ConversionSyntax'>]
```

Same crash occurs for: `"1,234.56"` (comma thousands separator), `"585,00"` (comma decimal), `"N/A"`, `"banana"`.

---

### `transactions_bad_date.json` — Category A

```json
"date": "15/03/2026"
```

DD/MM/YYYY format instead of ISO 8601. Django's date field calls `datetime.date.fromisoformat("15/03/2026")` which raises `ValueError`. **Entire batch fails.**

```
Error: ValueError: Invalid isoformat string: '15/03/2026'
```

Same crash for: `"March 15 2026"`, `"03-15-2026"`, `"2026/03/15"`.

---

### `invoices_silent_garbage.json` — Category B

Three problems, none caught:

| Field | Value | Why it passes | What goes wrong |
|---|---|---|---|
| `issue_date` | `"2026-03-31"` | Valid ISO date | — |
| `due_date` | `"2026-03-01"` | Valid ISO date | Due date is 30 days **before** issue date — no validation |
| `currency` | `"MOON"` | `get_or_create` creates any code | Invoice stored in fictional currency, never matches a real transaction |
| `total` | `"0.00"` | Valid decimal | Rule 5 divides by `abs(invoice_total)` → division by zero guarded, but Rule 4 amount check `txn.amount == 0` may fire unexpectedly |

---

### `transactions_silent_garbage.json` — Category B

| Field | Value | Why it passes | What goes wrong |
|---|---|---|---|
| `date` | `"9999-12-31"` | Valid ISO date | Transaction never appears in dashboard (default date filter ends today) |
| `amount` | `"0.00"` | Valid decimal | Rule 1 (`amount < 0`) does not fire, but amount=0 will match an invoice with total=0 |
| `currency` | `"MOON"` | `get_or_create` creates it | Currency mismatch with any real invoice |

---

## Steps

### Hard crash examples

```bash
BASE=http://localhost:8000/api

curl -X POST $BASE/ingest/invoices/ -F "file=@invoices_bad_amount.json"
# → 400 {"detail": "InvalidOperation ..."}

curl -X POST $BASE/ingest/transactions/ -F "file=@transactions_bad_date.json"
# → 400 {"detail": "ValueError: Invalid isoformat string: '15/03/2026'"}
```

Check **Ingestion Events** in Admin — a `status=failed` event is recorded for each.

### Silent garbage examples

```bash
curl -X POST $BASE/ingest/invoices/ -F "file=@invoices_silent_garbage.json"
# → 200 {"status": "success", "created": 1, ...}  ← no error

curl -X POST $BASE/ingest/transactions/ -F "file=@transactions_silent_garbage.json"
# → 200 {"status": "success", "created": 1, ...}  ← no error

curl -X POST $BASE/reconcile/
# Transaction SHOWCASE-10-TXN-2026-0002 matches SHOWCASE-10-INV-2026-0002
# Both amount=0 and both currency=MOON → Rule 4 fires, confidence 0.95, auto_matched
# But it's meaningless — zero-value MOON invoice "paid" by zero-value MOON transaction
```

Open the Dashboard, filter by `SHOWCASE-10-CUST-001` — the date `9999-12-31` falls outside any default date range, so the transaction may not appear at all until you clear the date filter.

## What this reveals

The ingestion service validates only two things at the record level: presence of `id` (explicit check) and parseable decimal/date values (implicit crash). It does not validate:

- Date ordering (`issue_date` < `due_date`)
- Sensible numeric ranges (non-zero total, positive amount for invoices)
- Known currency codes
- Dates within a reasonable range

Silent acceptance is the more dangerous failure mode — a hard crash is visible immediately; silently ingested garbage can corrupt reconciliation results and go unnoticed until a human reviews the output.
