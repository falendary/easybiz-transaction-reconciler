import { useState } from "react";
import { markUnrelated, type Match } from "../api";

interface Props {
  match: Match;
  onClose: () => void;
  onSaved: () => void;
}

export default function UnrelatedModal({ match, onClose, onSaved }: Props) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!note.trim()) { setError("Note is required."); return; }
    setSaving(true);
    setError(null);
    try {
      await markUnrelated(match.id, note.trim());
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
        <h3>Mark as Unrelated</h3>
        <div className="txn-meta">
          <strong>{match.transaction.transaction_id}</strong> &nbsp;·&nbsp;
          {match.transaction.amount} {match.transaction.currency.code} &nbsp;·&nbsp;
          {match.transaction.raw_counterparty}
        </div>

        <div className="field">
          <label>Reason (required)</label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Salary payment — not an invoice settlement"
            autoFocus
          />
        </div>

        {error && <div className="error-msg">{error}</div>}

        <div className="modal-footer">
          <button className="btn btn-gray" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Confirm Unrelated"}
          </button>
        </div>
      </div>
    </div>
  );
}
