"use client";

// Pipelines/stages (`product/crm/pipelines.py`). Create-only from this
// UI -- there is no PATCH/DELETE for a pipeline or stage in
// `product/crm/routes.py`, so no edit/delete control is offered for
// either (a real backend limitation, not an omission).
import { useState } from "react";
import { createPipeline, createStage, listPipelines, listStages, type Pipeline } from "@/lib/api/crm";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

function StagesList({ tenantId, pipeline }: { tenantId: string; pipeline: Pipeline }) {
  const stagesQuery = useApiQuery(() => listStages(tenantId, pipeline.id), [tenantId, pipeline.id]);
  const [name, setName] = useState("");
  const { state, run } = useAsyncAction(() =>
    createStage(tenantId, pipeline.id, {
      name,
      position: stagesQuery.status === "success" ? stagesQuery.data.length : 0,
    }),
  );

  return (
    <div style={{ marginTop: "var(--space-2)" }}>
      {stagesQuery.status === "loading" ? <LoadingState label="Loading stages…" /> : null}
      {stagesQuery.status === "error" ? (
        <ApiErrorPanel error={stagesQuery.error} onRetry={stagesQuery.refetch} />
      ) : null}
      {stagesQuery.status === "success" ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-1)", marginBottom: "var(--space-2)" }}>
          {stagesQuery.data.length === 0 ? (
            <span style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-faint)" }}>
              No stages yet.
            </span>
          ) : (
            stagesQuery.data
              .slice()
              .sort((a, b) => a.position - b.position)
              .map((stage) => (
                // Won/lost was carried entirely by the badge colour, so a
                // screen-reader user heard only the stage name and a
                // colour-blind user saw two similar chips. The outcome is
                // now in the text as well.
                <Badge key={stage.id} tone={stage.is_won ? "success" : stage.is_lost ? "danger" : "neutral"}>
                  {stage.name}
                  {stage.is_won ? " (won)" : stage.is_lost ? " (lost)" : ""}
                </Badge>
              ))
          )}
        </div>
      ) : null}
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim()) return;
          const created = await run();
          if (created) {
            setName("");
            stagesQuery.refetch();
          }
        }}
        style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}
      >
        <div style={{ flex: 1 }}>
          <Input
            label="New stage"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Negotiation"
          />
        </div>
        <Button type="submit" size="sm" disabled={state.status === "pending" || !name.trim()}>
          Add stage
        </Button>
      </form>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </div>
  );
}

export function PipelinesPanel({ tenantId }: { tenantId: string }) {
  const pipelinesQuery = useApiQuery(() => listPipelines(tenantId), [tenantId]);
  const [name, setName] = useState("");
  const { state, run } = useAsyncAction(() => createPipeline(tenantId, { name }));

  if (pipelinesQuery.status === "loading") return <LoadingState label="Loading pipelines…" />;
  if (pipelinesQuery.status === "error") {
    return <ApiErrorPanel error={pipelinesQuery.error} onRetry={pipelinesQuery.refetch} />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      {pipelinesQuery.data.length === 0 ? (
        <EmptyState title="No pipelines yet" description="Create a pipeline to start tracking opportunities." />
      ) : (
        pipelinesQuery.data.map((pipeline: Pipeline) => (
          <Card key={pipeline.id}>
            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
              <h2 style={{ margin: 0, fontSize: "var(--font-size-md)" }}>{pipeline.name}</h2>
              {pipeline.is_default ? <Badge tone="accent">Default</Badge> : null}
            </div>
            <StagesList tenantId={tenantId} pipeline={pipeline} />
          </Card>
        ))
      )}

      <Card>
        <h2 style={{ marginTop: 0, fontSize: "var(--font-size-md)" }}>Create a pipeline</h2>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (!name.trim()) return;
            const created = await run();
            if (created) {
              setName("");
              pipelinesQuery.refetch();
            }
          }}
          style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}
        >
          <div style={{ flex: 1 }}>
            <Input label="Pipeline name" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <Button type="submit" disabled={state.status === "pending" || !name.trim()}>
            Create
          </Button>
        </form>
        {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      </Card>
    </div>
  );
}
