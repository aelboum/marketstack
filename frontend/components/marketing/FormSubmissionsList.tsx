"use client";

// Submissions -- `GET .../forms/{id}/submissions`, pagination-only,
// read-only. `submitted_data` is visitor-supplied free text: rendered
// as plain React text nodes only, never dangerouslySetInnerHTML, same
// safety rule UI-4's MessageBody established for message content.
import { useState } from "react";
import { listFormSubmissions, type FormSubmission } from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

export function FormSubmissionsList({ tenantId, formId }: { tenantId: string; formId: string }) {
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => listFormSubmissions(tenantId, formId, { limit: PAGE_SIZE, offset }),
    [tenantId, formId, offset],
  );

  if (query.status === "loading") return <LoadingState label="Loading submissions…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return <EmptyState title="No submissions yet" description="Submissions to this form appear here." />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {query.data.results.map((submission: FormSubmission) => (
        <Card key={submission.id}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)", marginBottom: "var(--space-2)" }}>
            <span>{new Date(submission.created_at).toLocaleString()}</span>
            {submission.contact_id ? <span>Linked contact: {submission.contact_id}</span> : null}
          </div>
          <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "var(--space-1) var(--space-3)", margin: 0, fontSize: "var(--font-size-sm)" }}>
            {Object.entries(submission.submitted_data).map(([key, value]) => (
              <div key={key} style={{ display: "contents" }}>
                <dt style={{ color: "var(--color-text-muted)" }}>{key}</dt>
                <dd style={{ margin: 0 }}>{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ))}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
          Showing {offset + 1}–{offset + query.data.results.length}
        </span>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button variant="secondary" size="sm" onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))} disabled={offset === 0}>
            Previous
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setOffset((o) => o + PAGE_SIZE)} disabled={!query.data.hasMore}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
