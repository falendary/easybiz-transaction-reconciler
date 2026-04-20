import { useState } from "react";
import { deleteMatch, createManualMatch, type Match, type Invoice } from "../api";

interface Allocation {
  invoiceId: string;
  amount: string;
}

interface Props {
  match: Match;
  invoices: Invoice[];
  onClose: () => void;
  onSaved: () => void;
}

const EMPTY_ROW: Allocation = { invoiceId: "", amount: "" };

export default function ResolveModal({ match, invoices, onClose, onSaved }: Props) {
  const [rows, setRows] = useState<Allocation[]>([{ ...EMPTY_ROW }]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const txnAmount = parseFloat(match.transaction.amount);
  const allocated = rows.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0);
  const remaining = Math.round((txnAmount - allocated) * 100) / 100;

  const openInvoices = invoices.filter((i) =>
    i.status === "open" || i.status === "partially_paid"
  );

  function setRow(idx: number, patch: Partial<Allocation>) {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }

  function addRow() { setRows((prev) => [...prev, { ...EMPTY_ROW }]); }

  function removeRow(idx: number) {
    setRows((prev) => prev.filter((_, i) => i !== idx));
  }

  function invoiceLabel(inv: Invoice) {
    const tag = inv.type === "credit_note" ? "[CN] " : "";
    const cust = inv.customer?.name ?? "";
    return `${tag}${inv.invoice_id}  —  ${cust}  —  ${inv.currency} ${inv.total}  (${inv.status})`;
  }

  async function handleSave() {
    setError(null);

    for (const [i, row] of rows.entries()) {
      if (!row.invoiceId) { setError(`Row ${i + 1}: select an invoice.`); return; }
      if (!row.amount || isNaN(parseFloat(row.amount)) || parseFloat(row.amount) <= 0) {
        setError(`Row ${i + 1}: enter a valid amount.`); return;
      }
    }

    setSaving(true);
    try {
      // Remove the existing engine-generated match so the allocation check passes
      await deleteMatch(match.id);

      for (const row of rows) {
        const inv = openInvoices.find((i) => i.id === parseInt(row.invoiceId));
        if (!inv) throw new Error(`Invoice not found: ${row.invoiceId}`);
        await createManualMatch({
          transaction: match.transaction.id,
          invoice: inv.id,
          allocated_amount: parseFloat(row.amount).toFixed(2),
          note: note.trim(),
        });
      }

      onSaved();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Resolve Transaction</h3>
        <div className="txn-meta">
          <strong>{match.transaction.transaction_id}</strong> &nbsp;·&nbsp;
          <strong>{match.transaction.amount} {match.transaction.currency.code}</strong> &nbsp;·&nbsp;
          {match.transaction.raw_counterparty}
          {match.transaction.structured_reference && (
            <> &nbsp;·&nbsp; ref: <code>{match.transaction.structured_reference}</code></>
          )}
        </div>

        <div style={{ marginBottom: 8, fontSize: 12, color: "#555" }}>
          Allocate this transaction to one or more invoices. Credit notes (CN-) reduce the balance.
        </div>

        {rows.map((row, idx) => (
          <div className="alloc-row" key={idx}>
            <div>
              {idx === 0 && <label>Invoice / Credit Note</label>}
              <select
                value={row.invoiceId}
                onChange={(e) => setRow(idx, { invoiceId: e.target.value })}
              >
                <option value="">— Select invoice —</option>
                {openInvoices.map((inv) => (
                  <option key={inv.id} value={inv.id.toString()}>
                    {invoiceLabel(inv)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              {idx === 0 && <label>Amount</label>}
              <input
                type="number"
                step="0.01"
                min="0.01"
                placeholder="0.00"
                value={row.amount}
                onChange={(e) => setRow(idx, { amount: e.target.value })}
              />
            </div>
            <div style={{ display: "flex", alignItems: idx === 0 ? "flex-end" : "center", paddingBottom: idx === 0 ? 0 : undefined }}>
              <button
                className="remove-btn"
                onClick={() => removeRow(idx)}
                disabled={rows.length === 1}
                title="Remove row"
              >×</button>
            </div>
          </div>
        ))}

        <button className="btn btn-gray btn-sm" onClick={addRow} style={{ marginBottom: 12 }}>
          + Add invoice
        </button>

        <div className={`remaining ${remaining === 0 ? "remaining-ok" : "remaining-bad"}`}>
          Allocated: {allocated.toFixed(2)} &nbsp;·&nbsp;
          Remaining: {remaining.toFixed(2)} {match.transaction.currency.code}
          {remaining !== 0 && remaining > 0 && " ← unallocated remainder"}
          {remaining < 0 && " ← over-allocated"}
        </div>

        <div className="field">
          <label>Note (optional — recorded in audit trail)</label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Confirmed by client email 2026-03-20"
          />
        </div>

        {error && <div className="error-msg">{error}</div>}

        <div className="modal-footer">
          <button className="btn btn-gray" onClick={onClose} disabled={saving}>Cancel</button>
          <button
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || remaining < 0}
          >
            {saving ? "Saving…" : "Save Allocations"}
          </button>
        </div>
      </div>
    </div>
  );
}
