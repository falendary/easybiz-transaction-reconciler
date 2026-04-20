import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getIngestionEvents,
  getReconciliationRuns,
  uploadFile,
  runReconciliation,
  type IngestionEvent,
  type ReconciliationRun,
} from "../api";

interface UploadState {
  loading: boolean;
  result: Record<string, unknown> | null;
  error: string | null;
}

function UploadCard({
  label,
  accept,
  hint,
  endpoint,
  onDone,
}: {
  label: string;
  accept: string;
  hint: string;
  endpoint: string;
  onDone: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>({ loading: false, result: null, error: null });

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setState({ loading: true, result: null, error: null });
    try {
      const result = await uploadFile(endpoint, file);
      setState({ loading: false, result, error: null });
      onDone();
    } catch (e: unknown) {
      setState({ loading: false, result: null, error: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <div className="card">
      <h3>{label}</h3>
      <div className="upload-row">
        <label>{hint}</label>
        <input type="file" accept={accept} ref={fileRef} />
        <button className="btn btn-primary" disabled={state.loading} onClick={handleUpload}>
          {state.loading ? "Uploading…" : "Upload"}
        </button>
      </div>
      {state.error && <div className="error-msg">{state.error}</div>}
      {state.result && (
        <div className="success-msg">
          {JSON.stringify(state.result)
            .replace(/[{}"]/g, "")
            .replace(/,/g, " · ")
            .replace(/_/g, " ")}
        </div>
      )}
    </div>
  );
}

function statusBadge(status: string) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}

export default function IngestPage() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["events"] });

  const { data: events = [] } = useQuery<IngestionEvent[]>({
    queryKey: ["events"],
    queryFn: getIngestionEvents,
    refetchInterval: 5000,
  });

  const { data: runs = [] } = useQuery<ReconciliationRun[]>({
    queryKey: ["runs"],
    queryFn: getReconciliationRuns,
    refetchInterval: 5000,
  });

  const reconcileMut = useMutation({
    mutationFn: runReconciliation,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  const lastRun = runs[0] ?? null;

  return (
    <div className="page">
      <h2>Data Ingestion</h2>

      <UploadCard
        label="1. Upload Invoices"
        hint="invoices.json"
        accept=".json"
        endpoint="/ingest/invoices/"
        onDone={refresh}
      />
      <UploadCard
        label="2. Upload Transactions"
        hint="transactions.json"
        accept=".json"
        endpoint="/ingest/transactions/"
        onDone={refresh}
      />
      <UploadCard
        label="3. Upload Payout Report"
        hint="payout_report.csv"
        accept=".csv"
        endpoint="/ingest/payout/"
        onDone={refresh}
      />

      <div className="card">
        <h3>Reconciliation</h3>
        <div className="upload-row">
          <button
            className="btn btn-primary"
            disabled={reconcileMut.isPending}
            onClick={() => reconcileMut.mutate()}
          >
            {reconcileMut.isPending ? "Running…" : "Run Reconciliation"}
          </button>
          {reconcileMut.isError && (
            <span className="error-msg">{(reconcileMut.error as Error).message}</span>
          )}
        </div>
        {lastRun && (
          <div className="run-summary">
            Last run #{lastRun.id} — {statusBadge(lastRun.status)} &nbsp;
            processed <strong>{lastRun.total_processed}</strong> &nbsp;·&nbsp;
            auto_matched <strong>{lastRun.auto_matched_count}</strong> &nbsp;·&nbsp;
            needs_review <strong>{lastRun.needs_review_count}</strong> &nbsp;·&nbsp;
            skipped <strong>{lastRun.skipped_locked_count}</strong>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Upload History</h3>
        {events.length === 0 ? (
          <div className="empty">No uploads yet.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>#</th>
                <th>Type</th>
                <th>Filename</th>
                <th>Uploaded</th>
                <th>Status</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{e.id}</td>
                  <td>{e.file_type}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{e.filename}</td>
                  <td>{new Date(e.uploaded_at).toLocaleString()}</td>
                  <td>{statusBadge(e.status)}</td>
                  <td style={{ color: "#dc3545", fontSize: 12 }}>{e.error_message ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
