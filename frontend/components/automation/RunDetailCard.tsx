"use client";

// The run's own top-level fields, plus Cancel where the run is still
// in a non-terminal state (`queued`/`running`/`waiting` -- exactly
// `product/automation/durable/models.py`'s own
// `TERMINAL_RUN_STATUSES` complement, so this never offers to cancel a
// run the backend would already refuse).
import { useState } from "react";
import { cancelRun, type Run, type RunStatus } from "@/lib/api/automation";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

const STATUS_TONE: Record<RunStatus, "neutral" | "accent" | "success" | "danger" | "warning"> = {
  queued: "neutral",
  running: "accent",
  waiting: "accent",
  completed: "success",
  failed: "danger",
  cancelled: "warning",
};

const TERMINAL_STATUSES: RunStatus[] = ["completed", "failed", "cancelled"];

export function RunDetailCard({
  tenantId,
  run,
  onChanged,
}: {
  tenantId: string;
  run: Run;
  onChanged: (run: Run) => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { run: runCancel, state } = useAsyncAction(() => cancelRun(tenantId, run.id));
  const canCancel = !TERMINAL_STATUSES.includes(run.status);

  return (
    <Card>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "var(--space-2)",
          flexWrap: "wrap",
          marginBottom: "var(--space-3)",
        }}
      >
        <Badge tone={STATUS_TONE[run.status]}>{run.status}</Badge>
        {canCancel ? (
          <Button variant="danger" size="sm" onClick={() => setConfirmOpen(true)}>
            Cancel run
          </Button>
        ) : null}
      </div>

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "var(--space-1) var(--space-3)",
          margin: 0,
          fontSize: "var(--font-size-sm)",
        }}
      >
        <dt style={{ color: "var(--color-text-muted)" }}>Created</dt>
        <dd style={{ margin: 0 }}>{new Date(run.created_at).toLocaleString()}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Started</dt>
        <dd style={{ margin: 0 }}>{run.started_at ? new Date(run.started_at).toLocaleString() : "Not yet started"}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Completed</dt>
        <dd style={{ margin: 0 }}>{run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"}</dd>
        {run.waiting_for_event_type ? (
          <>
            <dt style={{ color: "var(--color-text-muted)" }}>Waiting for</dt>
            <dd style={{ margin: 0 }}>{run.waiting_for_event_type}</dd>
          </>
        ) : null}
      </dl>

      {run.error ? (
        <div style={{ marginTop: "var(--space-3)" }}>
          <InlineNotice tone="danger">{run.error}</InlineNotice>
        </div>
      ) : null}
      {state.status === "error" ? (
        <div style={{ marginTop: "var(--space-3)" }}>
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="Cancel this run?"
        description="Steps still in progress are stopped. This cannot be undone."
        confirmLabel="Cancel run"
        cancelLabel="Keep running"
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          const cancelled = await runCancel();
          setConfirmOpen(false);
          if (cancelled) onChanged(cancelled);
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </Card>
  );
}
