"use client";

// Automation detail. Composes the workflow's own identity/status, its
// version history (published + draft), and its runs -- three real,
// separately-fetched resources, not one flattened response (the API
// does not return them together).
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getWorkflow, type Run } from "@/lib/api/automation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { InlineNotice } from "@/components/ui/InlineNotice";
import {
  VersionsPanel,
  WorkflowStatusControl,
  RunsList,
  RunNowButton,
} from "@/components/automation";

export default function AutomationDetailPage() {
  const { tenantId, workflowId } = useParams<{ tenantId: string; workflowId: string }>();
  const [runsReloadKey, setRunsReloadKey] = useState(0);
  const [startedRunNotice, setStartedRunNotice] = useState<Run | null>(null);

  const workflowQuery = useApiQuery(() => getWorkflow(tenantId, workflowId), [tenantId, workflowId]);

  if (workflowQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading automation…" />
      </Page>
    );
  }
  if (workflowQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={workflowQuery.error} onRetry={workflowQuery.refetch} />
      </Page>
    );
  }

  const workflow = workflowQuery.data;

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/automation`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to automations
        </Link>
      </p>
      <PageHeader title={workflow.name} />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="status-heading">
          <h2 id="status-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Status
          </h2>
          <WorkflowStatusControl
            tenantId={tenantId}
            workflow={workflow}
            onChanged={() => workflowQuery.refetch()}
          />
        </section>

        <section aria-labelledby="configuration-heading">
          <h2 id="configuration-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Configuration
          </h2>
          <VersionsPanel tenantId={tenantId} workflowId={workflow.id} workflow={workflow} />
        </section>

        <section aria-labelledby="runs-heading">
          <h2 id="runs-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Runs
          </h2>
          <div style={{ marginBottom: "var(--space-3)" }}>
            <RunNowButton
              tenantId={tenantId}
              workflowId={workflow.id}
              disabled={!workflow.current_published_version_id}
              onStarted={(run) => {
                setStartedRunNotice(run);
                setRunsReloadKey((key) => key + 1);
              }}
            />
            {!workflow.current_published_version_id ? (
              <p style={{ margin: "var(--space-1) 0 0", fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
                Publish a version before running this automation.
              </p>
            ) : null}
            {startedRunNotice ? (
              <div style={{ marginTop: "var(--space-2)" }}>
                <InlineNotice tone="success" onDismiss={() => setStartedRunNotice(null)}>
                  Run started.{" "}
                  <Link href={`/t/${tenantId}/automation/runs/${startedRunNotice.id}`}>
                    View it
                  </Link>
                  .
                </InlineNotice>
              </div>
            ) : null}
          </div>
          <RunsList tenantId={tenantId} workflowId={workflow.id} reloadKey={runsReloadKey} />
        </section>
      </div>
    </Page>
  );
}
