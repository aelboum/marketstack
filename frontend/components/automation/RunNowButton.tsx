"use client";

// Manually starts a run -- `POST .../workflows/{id}/runs`. A real,
// separate capability from triggers: `trigger_type` gates automatic
// starts, but any published workflow can also be started directly
// (`context` defaults to an empty object on the backend, so this needs
// no form -- an arbitrary-JSON editor for `context` was deliberately
// left out; see this component's own note below).
//
// A manual run started with no context is a legitimate way to see what
// the automation actually does. For `update_contact`/`move_opportunity`
// specifically, the action reads `contact_id`/`opportunity_id` out of
// the *triggering event's* payload -- a manual run has no such event, so
// those two actions are expected to fail their step with a real
// backend error when run this way. That failure is not hidden: it shows
// up as a normal failed step on the run this button creates.
import { useState } from "react";
import { startRun, type Run } from "@/lib/api/automation";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function RunNowButton({
  tenantId,
  workflowId,
  disabled,
  onStarted,
}: {
  tenantId: string;
  workflowId: string;
  disabled?: boolean;
  onStarted: (run: Run) => void;
}) {
  const [dismissed, setDismissed] = useState(false);
  const { state, run } = useAsyncAction(() => startRun(tenantId, workflowId));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <Button
        variant="secondary"
        disabled={disabled || state.status === "pending"}
        onClick={async () => {
          setDismissed(false);
          const started = await run();
          if (started) onStarted(started);
        }}
      >
        {state.status === "pending" ? "Starting…" : "Run now"}
      </Button>
      {state.status === "error" && !dismissed ? (
        <InlineNotice tone="danger" onDismiss={() => setDismissed(true)}>
          {state.error.message}
        </InlineNotice>
      ) : null}
    </div>
  );
}
