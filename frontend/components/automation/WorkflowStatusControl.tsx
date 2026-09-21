"use client";

// Enable/disable -- `PATCH .../workflows/{id}/status`, the durable
// engine's only workflow-status transition (`active` <-> `paused`; the
// backend defines no other value, so this offers no other value).
//
// Activating asks for confirmation: once active, a published version
// with a real trigger starts acting on matching events immediately --
// exactly the "could unexpectedly activate a workflow" case the task
// calls out. Pausing has no such surprise (it only stops future
// activity), so it needs none.
import { useState } from "react";
import { setWorkflowStatus, type Workflow } from "@/lib/api/automation";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function WorkflowStatusControl({
  tenantId,
  workflow,
  onChanged,
}: {
  tenantId: string;
  workflow: Workflow;
  onChanged: (workflow: Workflow) => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { run, state } = useAsyncAction((next: "active" | "paused") =>
    setWorkflowStatus(tenantId, workflow.id, next),
  );

  const isActive = workflow.status === "active";
  const canActivate = Boolean(workflow.current_published_version_id);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone={isActive ? "success" : "neutral"}>{workflow.status}</Badge>
        {isActive ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={state.status === "pending"}
            onClick={async () => {
              const updated = await run("paused");
              if (updated) onChanged(updated);
            }}
          >
            {state.status === "pending" ? "Pausing…" : "Pause"}
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={state.status === "pending" || !canActivate}
            onClick={() => setConfirmOpen(true)}
            title={canActivate ? undefined : "Publish a version before activating this automation."}
          >
            Activate
          </Button>
        )}
      </div>
      {!isActive && !canActivate ? (
        <p style={{ margin: 0, fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Publish a version before activating this automation.
        </p>
      ) : null}
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}

      <ConfirmDialog
        open={confirmOpen}
        title="Activate this automation?"
        description="Once active, its published version starts acting on matching events right away."
        confirmLabel="Activate"
        pending={state.status === "pending"}
        onConfirm={async () => {
          const updated = await run("active");
          setConfirmOpen(false);
          if (updated) onChanged(updated);
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
