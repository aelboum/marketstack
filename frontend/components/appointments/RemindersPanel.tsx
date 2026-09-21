"use client";

// Manual reminder sweep -- `POST .../reminders/sweep`.
//
// Presented strictly as a manual action, because that is what it is: the
// route's own docstring states this endpoint "is never called by this
// product's own code", there being no scheduled-job capability to
// sanction a self-triggering sweep. Showing it as "reminders are on"
// would claim something the backend does not do.
//
// There is also no readable reminder state: `reminder_sent_at` lives on
// the appointment row but appears in no view, no response, and no
// history table. So this panel reports only what the sweep it just ran
// returned -- a count and the ids it touched -- and never implies a
// per-appointment reminder status it cannot see.
import { useState } from "react";
import { sweepReminders, type ReminderSweepResult } from "@/lib/api/appointments";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function RemindersPanel({ tenantId }: { tenantId: string }) {
  const [result, setResult] = useState<ReminderSweepResult | null>(null);
  const { run, state } = useAsyncAction(() => sweepReminders(tenantId));

  return (
    <Card>
      <p style={{ marginTop: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
        Sends an email reminder for every confirmed appointment starting within the next 24 hours
        that has not already been reminded. Nothing runs this automatically — it is a manual sweep,
        or one an external scheduler calls.
      </p>

      <Button
        disabled={state.status === "pending"}
        onClick={async () => {
          const swept = await run();
          if (swept) setResult(swept);
        }}
      >
        {state.status === "pending" ? "Sending…" : "Run reminder sweep"}
      </Button>

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}

      {result ? (
        <div style={{ marginTop: "var(--space-3)" }}>
          <InlineNotice tone="success">
            Sent {result.reminded_count} reminder{result.reminded_count === 1 ? "" : "s"}.
          </InlineNotice>
          {result.appointment_ids.length > 0 ? (
            <ul
              style={{
                margin: "var(--space-2) 0 0",
                paddingLeft: "var(--space-4)",
                fontSize: "var(--font-size-xs)",
                color: "var(--color-text-muted)",
              }}
            >
              {result.appointment_ids.map((id) => (
                <li key={id} style={{ wordBreak: "break-all" }}>
                  {id}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
