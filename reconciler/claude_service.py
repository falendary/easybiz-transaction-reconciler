"""Claude AI fallback for transaction matching.

Only this module may import the anthropic SDK.
Called by reconciliation_service._rule9_ai when ENABLE_AI_MATCHING=true.
"""

import json
from decimal import Decimal
from typing import Optional

import anthropic
from django.conf import settings

from reconciler.models import Invoice, Transaction

_SYSTEM_PROMPT = (
    "You are a financial reconciliation assistant. "
    "Given a bank transaction and a list of open invoices, "
    "identify the single best matching invoice (if any). "
    "Respond with a JSON object only — no prose, no markdown fences. "
    "Schema: {\"invoice_id\": \"<id or null>\", \"confidence\": <0.0-1.0>, \"note\": \"<reason>\"}"
)

_MAX_CANDIDATES = 20


def ai_match_transaction(
    txn: Transaction,
    candidates: list[Invoice],
) -> Optional[tuple[Invoice, float, str]]:
    """Ask Claude to pick the best invoice match for a transaction.

    Parameters:
        txn: The transaction to match.
        candidates: Open/partially_paid invoices to consider.

    Returns:
        (invoice, confidence, note) if a match is found, else None.

    Raises:
        anthropic.APIError: propagated on network / auth failures.
    """
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    invoice_summaries = [
        {
            "invoice_id": inv.invoice_id,
            "customer": inv.customer.name,
            "total": str(inv.total),
            "currency": inv.currency.code,
            "status": inv.status,
        }
        for inv in candidates[:_MAX_CANDIDATES]
    ]

    user_message = json.dumps({
        "transaction": {
            "id": txn.transaction_id,
            "date": str(txn.date),
            "amount": str(txn.amount),
            "currency": txn.currency.code,
            "counterparty": txn.raw_counterparty,
            "structured_reference": txn.structured_reference,
            "description": txn.description,
        },
        "open_invoices": invoice_summaries,
    })

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=256,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    invoice_id = parsed.get("invoice_id")
    confidence = float(parsed.get("confidence", 0.0))
    note = parsed.get("note", "")

    if not invoice_id:
        return None

    matched = next((inv for inv in candidates if inv.invoice_id == invoice_id), None)
    if matched is None:
        return None

    return matched, confidence, note
