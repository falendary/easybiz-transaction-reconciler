# AI Workflow

How AI was used during the build of this project — tools, process, one override, one save.

---

## Tools used

**Claude (Anthropic)** — primary coding assistant, used via Claude Code CLI throughout the entire build.

**Claude API** — also embedded in the product itself: Rule 9 of the reconciliation engine calls `claude-opus-4-7` as a last-resort fallback when no rule-based match is found. The API key is set via `ANTHROPIC_API_KEY` in `.env`; the feature is off by default (`ENABLE_AI_MATCHING=false`).

---

## Process

### Upfront specification before any code

Before the first line was written, three documents were prepared explicitly:

- **Models** — all 16 entities with field names, types, relationships, and the purpose of each model
- **API endpoints** — every route, HTTP method, request/response shape, and error cases
- **User scenarios and edge cases** — the full reconciliation rule set, what should auto-match, what should land in review, what is explicitly out of scope

This front-loading paid off: Claude had enough context to generate correct code on the first attempt for most issues, and disagreements about behaviour were resolved in the spec rather than in diffs.

### Plan Mode for architecture, issue-by-issue for implementation

Claude Code's Plan Mode was used heavily before starting. The full architecture — app structure, service layer pattern, rule priority order, confidence threshold, idempotency guarantees — was locked in as a plan before any issue was opened. This prevented scope creep and kept each implementation step focused.

Issues were executed strictly in order (1 → 7), each on its own branch. Claude worked through one issue at a time: read the spec, implement, write tests, move on. No issue was left partially open while starting the next.

---

## One moment the AI was overridden

**Rule 7 — partial payment grouping.**

The original engine implementation treated each transaction independently. When a €585 invoice had two partial payments (€300 + €285), each transaction was evaluated alone: €300 ≠ €585 → confidence 0.75 → `needs_review`. Showcase 02 was designed to demonstrate a success case, but both transactions landed in review.

Claude's initial approach was correct by the spec as written — each transaction is matched individually. But the intended user experience was that once the second payment arrived and both were in the system, reconciliation should resolve the group automatically without human intervention.

The override: extend Rule 7 to aggregate all transactions sharing the same `structured_reference` and compare their sum to the invoice total. If the sum matches exactly, upgrade confidence to 0.95 and auto-match all of them. This required adding a `Sum` aggregate query inside the rule and re-testing idempotency. Claude implemented the change cleanly once the intent was stated explicitly, but would not have proposed it unprompted — the original spec said nothing about grouped re-evaluation.

---

## One moment the AI saved hours

**The customer filter bug on the reconciliation dashboard.**

The dashboard had a customer dropdown filter. Filtering by a specific customer caused all `needs_review` matches to disappear from the table, even when that customer had open transactions.

The root cause was subtle: `needs_review` matches that did not yet have an invoice (no rule fired, `invoice=NULL`) were being excluded by the filter `invoice__customer__customer_id=X` because the `invoice` foreign key was null. Django silently turned this into an `INNER JOIN`, dropping all unmatched rows.

Claude identified the problem immediately when shown the filter logic and the empty table symptom: the fix required splitting the customer filter into two separate `Q` objects — `by_invoice` for the reconciled table (where an invoice always exists), and `by_invoice | by_counterparty` for the needs-review table (where `icontains` on `raw_counterparty` catches unmatched transactions). Diagnosing this manually would have required stepping through Django's ORM query generation or reading the generated SQL — easily 30–60 minutes. Claude surfaced the cause in one exchange.

