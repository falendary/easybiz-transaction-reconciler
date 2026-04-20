import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getMatches,
  getCustomers,
  getInvoices,
  confirmMatch,
  rejectMatch,
  type Match,
  type Customer,
  type Invoice,
} from "../api";
import ResolveModal from "../components/ResolveModal";
import UnrelatedModal from "../components/UnrelatedModal";


function ConfidenceCell({ score }: { score: string }) {
  const n = parseFloat(score);
  const cls = n >= 0.85 ? "conf-high" : n >= 0.7 ? "conf-mid" : "conf-low";
  return <span className={cls}>{score}</span>;
}

function Badge({ value }: { value: string }) {
  return <span className={`badge badge-${value}`}>{value.replace(/_/g, " ")}</span>;
}

function useMatchFilter(matches: Match[], dateFrom: string, dateTo: string, customer: string) {
  return matches.filter((m) => {
    if (dateFrom && m.transaction.date < dateFrom) return false;
    if (dateTo && m.transaction.date > dateTo) return false;
    if (customer) {
      const custId = m.invoice?.customer?.id?.toString() ?? "";
      if (custId !== customer) return false;
    }
    return true;
  });
}

export default function DashboardPage() {
  const qc = useQueryClient();
  const today = new Date();
  const yearAgo = new Date(today);
  yearAgo.setFullYear(today.getFullYear() - 1);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);

  const [dateFrom, setDateFrom] = useState(fmt(yearAgo));
  const [dateTo, setDateTo] = useState(fmt(today));
  const [customer, setCustomer] = useState("");
  const [resolveMatch, setResolveMatch] = useState<Match | null>(null);
  const [unrelatedMatch, setUnrelatedMatch] = useState<Match | null>(null);

  const { data: reviewMatches = [], isLoading: loadingReview } = useQuery<Match[]>({
    queryKey: ["matches", "needs_review"],
    queryFn: () => getMatches("needs_review"),

  });

  const { data: reconciledMatches = [], isLoading: loadingReconciled } = useQuery<Match[]>({
    queryKey: ["matches", "reconciled"],
    queryFn: () => getMatches("auto_matched", "confirmed", "manually_matched"),
  });

  const { data: customers = [] } = useQuery<Customer[]>({
    queryKey: ["customers"],
    queryFn: getCustomers,
  });

  const { data: invoices = [] } = useQuery<Invoice[]>({
    queryKey: ["invoices"],
    queryFn: getInvoices,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["matches"] });

  const confirmMut = useMutation({ mutationFn: confirmMatch, onSuccess: invalidate });
  const rejectMut = useMutation({ mutationFn: rejectMatch, onSuccess: invalidate });

  const filteredReview = useMatchFilter(reviewMatches, dateFrom, dateTo, customer);
  const filteredReconciled = useMatchFilter(reconciledMatches, dateFrom, dateTo, customer);
  const quickBusy = confirmMut.isPending || rejectMut.isPending;

  return (
    <div className="page">
      <h2>Reconciliation Dashboard</h2>

      <div className="filter-bar">
        <div>
          <label>Date from</label>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div>
          <label>Date to</label>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div>
          <label>Client</label>
          <select value={customer} onChange={(e) => setCustomer(e.target.value)}>
            <option value="">— All clients —</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id.toString()}>{c.name}</option>
            ))}
          </select>
        </div>
        <button className="btn btn-gray" onClick={() => { setDateFrom(fmt(yearAgo)); setDateTo(fmt(today)); setCustomer(""); }}>
          Clear
        </button>
      </div>

      {/* ── Needs Review ── */}
      <div className="card">
        <h3>Needs Review ({filteredReview.length})</h3>
        {loadingReview ? (
          <div className="empty">Loading…</div>
        ) : filteredReview.length === 0 ? (
          <div className="empty">No transactions need review. 🎉</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Date</th>
                <th>Transaction</th>
                <th>Amount</th>
                <th>Counterparty</th>
                <th>Reference</th>
                <th>Invoice</th>
                <th>Type</th>
                <th>Conf.</th>
                <th>Reason</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredReview.map((m) => (
                <tr key={m.id}>
                  <td>{m.transaction.date}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{m.transaction.transaction_id}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {m.transaction.amount} {m.transaction.currency.code}
                  </td>
                  <td title={m.transaction.raw_counterparty}>
                    {m.transaction.raw_counterparty.slice(0, 28)}
                    {m.transaction.raw_counterparty.length > 28 ? "…" : ""}
                  </td>
                  <td style={{ fontSize: 11, color: "#555" }}>
                    {m.transaction.structured_reference ?? "—"}
                  </td>
                  <td>
                    {m.invoice ? (
                      <>
                        <span style={{ fontFamily: "monospace", fontSize: 12 }}>{m.invoice.invoice_id}</span>
                        {m.invoice.customer && (
                          <><br /><span style={{ fontSize: 11, color: "#888" }}>{m.invoice.customer.name}</span></>
                        )}
                      </>
                    ) : "—"}
                  </td>
                  <td><Badge value={m.match_type} /></td>
                  <td><ConfidenceCell score={m.confidence_score} /></td>
                  <td style={{ fontSize: 11, color: "#666", maxWidth: 180 }}>{m.note ?? "—"}</td>
                  <td>
                    <div className="gap" style={{ flexWrap: "wrap" }}>
                      <button
                        className="btn btn-sm btn-green"
                        disabled={quickBusy}
                        onClick={() => confirmMut.mutate(m.id)}
                        title="Confirm the engine's suggestion"
                      >✓ Confirm</button>
                      <button
                        className="btn btn-sm btn-red"
                        disabled={quickBusy}
                        onClick={() => rejectMut.mutate(m.id)}
                        title="Reject the engine's suggestion"
                      >✗ Reject</button>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={quickBusy}
                        onClick={() => setResolveMatch(m)}
                        title="Manually allocate to invoices (split, partial, credit note)"
                      >⊕ Resolve</button>
                      <button
                        className="btn btn-sm btn-gray"
                        disabled={quickBusy}
                        onClick={() => setUnrelatedMatch(m)}
                        title="Mark as unrelated — requires a note"
                      >~ Unrelated</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Reconciled ── */}
      <div className="card">
        <h3>Reconciled ({filteredReconciled.length})</h3>
        {loadingReconciled ? (
          <div className="empty">Loading…</div>
        ) : filteredReconciled.length === 0 ? (
          <div className="empty">No reconciled matches yet.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Date</th>
                <th>Transaction</th>
                <th>Amount</th>
                <th>Counterparty</th>
                <th>Invoice</th>
                <th>Client</th>
                <th>Allocated</th>
                <th>Type</th>
                <th>Status</th>
                <th>Conf.</th>
              </tr>
            </thead>
            <tbody>
              {filteredReconciled.map((m) => (
                <tr key={m.id} className="row-matched">
                  <td>{m.transaction.date}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{m.transaction.transaction_id}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {m.transaction.amount} {m.transaction.currency.code}
                  </td>
                  <td title={m.transaction.raw_counterparty}>
                    {m.transaction.raw_counterparty.slice(0, 22)}
                    {m.transaction.raw_counterparty.length > 22 ? "…" : ""}
                  </td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{m.invoice?.invoice_id ?? "—"}</td>
                  <td style={{ fontSize: 12 }}>{m.invoice?.customer?.name?.slice(0, 20) ?? "—"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{m.allocated_amount}</td>
                  <td><Badge value={m.match_type} /></td>
                  <td><Badge value={m.status} /></td>
                  <td><ConfidenceCell score={m.confidence_score} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {resolveMatch && (
        <ResolveModal
          match={resolveMatch}
          invoices={invoices}
          onClose={() => setResolveMatch(null)}
          onSaved={invalidate}
        />
      )}

      {unrelatedMatch && (
        <UnrelatedModal
          match={unrelatedMatch}
          onClose={() => setUnrelatedMatch(null)}
          onSaved={invalidate}
        />
      )}
    </div>
  );
}
