"use client";

// Run detail. `GET .../runs/{id}` is tenant+run scoped directly (not
// nested under a workflow id in the real route), so this page lives at
// `/automation/runs/[runId]`, matching the API's own shape rather than
// inventing a `/automation/[workflowId]/runs/[runId]` nesting the
// backend doesn't have.
import Link from "next/link";
import { useParams } from "next/navigation";
import { getRun } from "@/lib/api/automation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { RunDetailCard, RunStepsList } from "@/components/automation";

export default function AutomationRunDetailPage() {
  const { tenantId, runId } = useParams<{ tenantId: string; runId: string }>();
  const runQuery = useApiQuery(() => getRun(tenantId, runId), [tenantId, runId]);

  if (runQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading run…" />
      </Page>
    );
  }
  if (runQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={runQuery.error} onRetry={runQuery.refetch} />
      </Page>
    );
  }

  const run = runQuery.data;

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/automation/${run.workflow_id}`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to automation
        </Link>
      </p>
      <PageHeader title="Run detail" />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="run-heading">
          <h2 id="run-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Run
          </h2>
          <RunDetailCard tenantId={tenantId} run={run} onChanged={() => runQuery.refetch()} />
        </section>

        <section aria-labelledby="steps-heading">
          <h2 id="steps-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Steps
          </h2>
          <RunStepsList tenantId={tenantId} runId={run.id} />
        </section>
      </div>
    </Page>
  );
}
