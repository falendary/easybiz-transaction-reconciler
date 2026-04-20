const BASE = "/api";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function uploadFile(path: string, file: File) {
  const fd = new FormData();
  fd.append("file", file);
  return apiFetch<Record<string, unknown>>(path, { method: "POST", body: fd });
}

export interface IngestionEvent {
  id: number;
  file_type: string;
  filename: string;
  uploaded_at: string;
  status: string;
  error_message: string | null;
}

export interface Customer {
  id: number;
  customer_id: string;
  name: string;
}

export interface MatchTransaction {
  id: number;
  transaction_id: string;
  date: string;
  amount: string;
  currency: { code: string };
  raw_counterparty: string;
  structured_reference: string | null;
}

export interface MatchInvoice {
  id: number;
  invoice_id: string;
  customer: { id: number; name: string } | null;
}

export interface Match {
  id: number;
  transaction: MatchTransaction;
  invoice: MatchInvoice | null;
  allocated_amount: string;
  confidence_score: string;
  match_type: string;
  status: string;
  note: string | null;
}

export interface ReconciliationRun {
  id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  total_processed: number;
  auto_matched_count: number;
  needs_review_count: number;
  skipped_locked_count: number;
}

export const getIngestionEvents = () =>
  apiFetch<IngestionEvent[]>("/ingest/events/");

export const getCustomers = () =>
  apiFetch<Customer[]>("/customers/");

export const getMatches = (...statuses: string[]) => {
  const qs = statuses.map((s) => `status=${s}`).join("&");
  return apiFetch<Match[]>(`/matches/?${qs}`);
};

export const getReconciliationRuns = () =>
  apiFetch<ReconciliationRun[]>("/reconcile/runs/");

export const runReconciliation = () =>
  apiFetch<ReconciliationRun>("/reconcile/", { method: "POST" });

export interface Invoice {
  id: number;
  invoice_id: string;
  type: string;
  customer: { id: number; name: string } | null;
  total: string;
  status: string;
  currency: string;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export const confirmMatch = (id: number) =>
  apiFetch<Match>(`/matches/${id}/confirm/`, { method: "POST", headers: JSON_HEADERS, body: "{}" });

export const rejectMatch = (id: number) =>
  apiFetch<Match>(`/matches/${id}/reject/`, { method: "POST", headers: JSON_HEADERS, body: "{}" });

export const markUnrelated = (id: number, note: string) =>
  apiFetch<Match>(`/matches/${id}/mark-unrelated/`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ note }) });

export const deleteMatch = (id: number): Promise<void> =>
  fetch(`${BASE}/matches/${id}/`, { method: "DELETE" }).then((r) => {
    if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
  });

export const getInvoices = () =>
  apiFetch<Invoice[]>("/invoices/");

export const createManualMatch = (data: {
  transaction: number;
  invoice: number;
  allocated_amount: string;
  note: string;
}) =>
  apiFetch<Match>("/matches/", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(data) });
