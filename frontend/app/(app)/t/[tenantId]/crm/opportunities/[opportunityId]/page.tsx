"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  changeOpportunityStage,
  deleteOpportunity,
  getOpportunity,
  listStages,
} from "@/lib/api/crm";
import { formatMoney } from "@/lib/crm/money";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { OpportunityForm, ActivitiesPanel, TagsPanel, CustomFieldsPanel } from "@/components/crm";

function StageChanger({
  tenantId,
  opportunityId,
  pipelineId,
  currentStageId,
  onChanged,
}: {
  tenantId: string;
  opportunityId: string;
  pipelineId: string;
  currentStageId: string;
  onChanged: () => void;
}) {
  const stagesQuery = useApiQuery(() => listStages(tenantId, pipelineId), [tenantId, pipelineId]);
  const { run, state } = useAsyncAction((stageId: string) =>
    changeOpportunityStage(tenantId, opportunityId, stageId),
  );

  if (stagesQuery.status !== "success") return null;

  return (
    <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}>
      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Stage</span>
        <select
          value={currentStageId}
          disabled={state.status === "pending"}
          onChange={async (event) => {
            await run(event.target.value);
            onChanged();
          }}
        >
          {stagesQuery.data.map((stage) => (
            <option key={stage.id} value={stage.id}>
              {stage.name}
            </option>
          ))}
        </select>
      </label>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </div>
  );
}

export default function OpportunityDetailPage() {
  const params = useParams<{ tenantId: string; opportunityId: string }>();
  const { tenantId, opportunityId } = params;
  const router = useRouter();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const query = useApiQuery(() => getOpportunity(tenantId, opportunityId), [tenantId, opportunityId]);
  const { run: runDelete, state: deleteState } = useAsyncAction(() =>
    deleteOpportunity(tenantId, opportunityId),
  );

  if (query.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading opportunity…" />
      </Page>
    );
  }
  if (query.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={query.error} onRetry={query.refetch} />
      </Page>
    );
  }

  const opportunity = query.data;

  return (
    <Page>
      <PageHeader
        title={opportunity.name}
        description={formatMoney(opportunity.amount)}
        actions={
          <Button variant="danger" onClick={() => setConfirmDeleteOpen(true)}>
            Delete
          </Button>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="stage-heading">
          <h2 id="stage-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Stage
          </h2>
          <Card>
            <StageChanger
              tenantId={tenantId}
              opportunityId={opportunity.id}
              pipelineId={opportunity.pipeline_id}
              currentStageId={opportunity.stage_id}
              onChanged={query.refetch}
            />
          </Card>
        </section>

        <section aria-labelledby="details-heading">
          <h2 id="details-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Details
          </h2>
          <Card>
            <OpportunityForm tenantId={tenantId} opportunity={opportunity} onSaved={query.refetch} />
          </Card>
        </section>

        <section aria-labelledby="tags-heading">
          <h2 id="tags-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Tags
          </h2>
          <Card>
            <TagsPanel tenantId={tenantId} entityType="opportunity" entityId={opportunity.id} />
          </Card>
        </section>

        <section aria-labelledby="fields-heading">
          <h2 id="fields-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Custom fields
          </h2>
          <Card>
            <CustomFieldsPanel tenantId={tenantId} entityType="opportunity" entityId={opportunity.id} />
          </Card>
        </section>

        <section aria-labelledby="activity-heading">
          <h2 id="activity-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Activity
          </h2>
          <ActivitiesPanel tenantId={tenantId} parent={{ opportunityId: opportunity.id }} />
        </section>
      </div>

      {deleteState.status === "error" ? (
        <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this opportunity?"
        description="This cannot be undone."
        confirmLabel="Delete"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          router.push(`/t/${tenantId}/crm/opportunities`);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Page>
  );
}
