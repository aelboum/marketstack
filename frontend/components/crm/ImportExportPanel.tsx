"use client";

// Contact import/export (`product/crm/imports.py`, Phase 4.5) --
// contacts only; there is no import/export route for companies or
// opportunities in `product/crm/routes.py`. Import is a background job
// (`POST .../contact-imports` enqueues, `GET .../imports/{id}` reports
// status: pending -> running -> completed|failed) -- this panel polls
// the real job status rather than assuming completion; export is a
// synchronous `text/csv` response, not a job.
import { useEffect, useRef, useState } from "react";
import { exportContactsCsv, getImportJob, importContacts, type ImportJob } from "@/lib/api/crm";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { Badge } from "@/components/ui/Badge";

// Mirrors `product/crm/imports.py::MAX_IMPORT_FILE_SIZE_BYTES` exactly
// (the actual, enforced backend limit) -- checked here so an
// over-limit paste is caught before a submit round-trip, not to
// silently truncate legitimate content short of the real limit.
const MAX_IMPORT_FILE_SIZE_BYTES = 5 * 1024 * 1024;
const TERMINAL_STATUSES = new Set(["completed", "failed"]);

function ImportSection({ tenantId }: { tenantId: string }) {
  const [csvContent, setCsvContent] = useState("");
  const [job, setJob] = useState<ImportJob | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { state, run } = useAsyncAction((content: string) => importContacts(tenantId, content));
  const csvBytes = new TextEncoder().encode(csvContent).length;
  const overLimit = csvBytes > MAX_IMPORT_FILE_SIZE_BYTES;

  useEffect(() => {
    if (!job || TERMINAL_STATUSES.has(job.status)) return;
    pollRef.current = setInterval(async () => {
      const updated = await getImportJob(tenantId, job.id);
      setJob(updated);
      if (TERMINAL_STATUSES.has(updated.status) && pollRef.current) {
        clearInterval(pollRef.current);
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [job, tenantId]);

  return (
    <Card>
      <h3 style={{ marginTop: 0 }}>Import contacts</h3>
      <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
        Paste CSV content below (no file-upload endpoint exists yet -- see this phase&apos;s
        deferred items).
      </p>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!csvContent.trim() || overLimit) return;
          const created = await run(csvContent);
          if (created) setJob(created);
        }}
        style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
      >
        <textarea
          value={csvContent}
          onChange={(event) => setCsvContent(event.target.value)}
          rows={6}
          aria-label="CSV content"
          placeholder="first_name,last_name,email,phone
Jane,Doe,jane@example.com,+15551234567"
          style={{
            fontFamily: "monospace",
            fontSize: "var(--font-size-sm)",
            padding: "var(--space-2)",
            border: `1px solid ${overLimit ? "var(--color-danger)" : "var(--color-border-strong)"}`,
            borderRadius: "var(--radius-sm)",
          }}
        />
        <span style={{ fontSize: "var(--font-size-xs)", color: overLimit ? "var(--color-danger)" : "var(--color-text-faint)" }}>
          {(csvBytes / 1024).toFixed(1)} KB of {(MAX_IMPORT_FILE_SIZE_BYTES / 1024 / 1024).toFixed(0)} MB limit
        </span>
        <Button type="submit" disabled={state.status === "pending" || !csvContent.trim() || overLimit}>
          {state.status === "pending" ? "Submitting…" : "Import"}
        </Button>
      </form>
      {overLimit ? (
        <InlineNotice tone="danger">
          Content exceeds the {(MAX_IMPORT_FILE_SIZE_BYTES / 1024 / 1024).toFixed(0)} MB import limit.
        </InlineNotice>
      ) : null}
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      {job ? (
        <div style={{ marginTop: "var(--space-3)" }}>
          <InlineNotice tone={job.status === "failed" ? "danger" : job.status === "completed" ? "success" : "neutral"}>
            Job status: <Badge>{job.status}</Badge>
            {TERMINAL_STATUSES.has(job.status) ? (
              <span style={{ marginLeft: "var(--space-2)" }}>
                {job.succeeded_rows} succeeded, {job.failed_rows} failed
                {job.total_rows != null ? ` of ${job.total_rows}` : ""}.
              </span>
            ) : (
              " — checking…"
            )}
          </InlineNotice>
        </div>
      ) : null}
    </Card>
  );
}

function ExportSection({ tenantId }: { tenantId: string }) {
  const { state, run } = useAsyncAction(() => exportContactsCsv(tenantId));

  return (
    <Card>
      <h3 style={{ marginTop: 0 }}>Export contacts</h3>
      <Button
        variant="secondary"
        disabled={state.status === "pending"}
        onClick={async () => {
          const csv = await run();
          if (csv === undefined) return;
          const blob = new Blob([csv], { type: "text/csv" });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = "contacts.csv";
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
        }}
      >
        {state.status === "pending" ? "Exporting…" : "Download CSV"}
      </Button>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </Card>
  );
}

export function ImportExportPanel({ tenantId }: { tenantId: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <ImportSection tenantId={tenantId} />
      <ExportSection tenantId={tenantId} />
    </div>
  );
}
