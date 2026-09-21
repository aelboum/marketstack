"use client";

// One appointment, plus the only two state changes the backend exposes
// for staff: cancel and reschedule.
//
// This renders an appointment the caller already holds -- there is no
// fetch here, because there is no authenticated read endpoint to fetch
// from (see lib/api/appointments.ts's module docstring). An appointment
// reaches this component exactly three ways: it was just booked, just
// cancelled, or just rescheduled, and each of those three POSTs returns
// the row it touched.
//
// The four outcomes the task's cancellation spec distinguishes map onto
// real backend responses, and none of them is hidden:
//   - requested   -> `pending` on the confirm dialog;
//   - succeeded   -> the returned row comes back `status: "cancelled"`;
//   - rejected    -> a 404 (non-enumerating: "missing" and "forbidden"
//                    are the same response by design) or a 403, rendered
//                    verbatim, never softened into "something went wrong";
//   - already cancelled / invalid state -> the backend's own 400
//                    ("appointment ... is already cancelled.",
//                    "... cannot be rescheduled while status=...").
// A reschedule that collides with another confirmed appointment comes
// back 409 with a fixed, detail-free message; it is called out
// explicitly because "pick a different time" is a different instruction
// than "this failed".
import { useState } from "react";
import {
  cancelAppointment,
  rescheduleAppointment,
  type Appointment,
} from "@/lib/api/appointments";
import { isoToLocalInput, localInputToIso } from "@/lib/appointments/datetime";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function AppointmentCard({
  tenantId,
  appointment,
  onChanged,
}: {
  tenantId: string;
  appointment: Appointment;
  onChanged?: (appointment: Appointment) => void;
}) {
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const [rescheduling, setRescheduling] = useState(false);
  const [newStart, setNewStart] = useState(isoToLocalInput(appointment.starts_at));
  const [newEnd, setNewEnd] = useState(isoToLocalInput(appointment.ends_at));

  const { run: runCancel, state: cancelState } = useAsyncAction(() =>
    cancelAppointment(tenantId, appointment.id),
  );
  const { run: runReschedule, state: rescheduleState } = useAsyncAction(() => {
    const startsAt = localInputToIso(newStart);
    const endsAt = localInputToIso(newEnd);
    return rescheduleAppointment(tenantId, appointment.id, {
      new_starts_at: startsAt as string,
      new_ends_at: endsAt as string,
    });
  });

  const isCancelled = appointment.status === "cancelled";
  const startIso = localInputToIso(newStart);
  const endIso = localInputToIso(newEnd);
  const rescheduleValid =
    startIso !== null && endIso !== null && new Date(endIso) > new Date(startIso);

  return (
    <Card>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "var(--space-2)",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <Badge tone={isCancelled ? "warning" : "success"}>{appointment.status}</Badge>
          <strong style={{ fontSize: "var(--font-size-sm)" }}>
            {new Date(appointment.starts_at).toLocaleString()} –{" "}
            {new Date(appointment.ends_at).toLocaleTimeString()}
          </strong>
        </div>
        {isCancelled ? null : (
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <Button variant="secondary" size="sm" onClick={() => setRescheduling((v) => !v)}>
              {rescheduling ? "Cancel reschedule" : "Reschedule"}
            </Button>
            <Button variant="danger" size="sm" onClick={() => setConfirmCancelOpen(true)}>
              Cancel appointment
            </Button>
          </div>
        )}
      </div>

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "var(--space-1) var(--space-3)",
          margin: "var(--space-3) 0 0",
          fontSize: "var(--font-size-sm)",
        }}
      >
        <dt style={{ color: "var(--color-text-muted)" }}>Appointment ID</dt>
        <dd style={{ margin: 0, wordBreak: "break-all" }}>{appointment.id}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Calendar ID</dt>
        <dd style={{ margin: 0, wordBreak: "break-all" }}>{appointment.calendar_id}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Contact ID</dt>
        <dd style={{ margin: 0, wordBreak: "break-all" }}>{appointment.contact_id ?? "—"}</dd>
      </dl>

      {isCancelled ? (
        <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          This appointment is cancelled. Cancelled appointments cannot be rescheduled, and no longer
          block their slot.
        </p>
      ) : null}

      {rescheduling && !isCancelled ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (!rescheduleValid) return;
            const updated = await runReschedule();
            if (updated) {
              setRescheduling(false);
              onChanged?.(updated);
            }
          }}
          style={{
            display: "flex",
            gap: "var(--space-2)",
            alignItems: "flex-end",
            flexWrap: "wrap",
            marginTop: "var(--space-3)",
          }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              New start
            </span>
            <input
              aria-label="New start"
              type="datetime-local"
              value={newStart}
              onChange={(event) => setNewStart(event.target.value)}
              style={{
                padding: "var(--space-2)",
                border: "1px solid var(--color-border-strong)",
                borderRadius: "var(--radius-sm)",
              }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              New end
            </span>
            <input
              aria-label="New end"
              type="datetime-local"
              value={newEnd}
              onChange={(event) => setNewEnd(event.target.value)}
              style={{
                padding: "var(--space-2)",
                border: "1px solid var(--color-border-strong)",
                borderRadius: "var(--radius-sm)",
              }}
            />
          </label>
          <Button type="submit" disabled={rescheduleState.status === "pending" || !rescheduleValid}>
            {rescheduleState.status === "pending" ? "Rescheduling…" : "Confirm new time"}
          </Button>
        </form>
      ) : null}

      {rescheduleState.status === "error" ? (
        <InlineNotice tone="danger">
          {rescheduleState.error.status === 409
            ? "That time is no longer available. Pick a different slot."
            : rescheduleState.error.message}
        </InlineNotice>
      ) : null}
      {cancelState.status === "error" ? (
        <InlineNotice tone="danger">{cancelState.error.message}</InlineNotice>
      ) : null}

      <ConfirmDialog
        open={confirmCancelOpen}
        title="Cancel this appointment?"
        description="The contact's booking is cancelled and the slot becomes bookable again. This cannot be undone."
        confirmLabel="Cancel appointment"
        cancelLabel="Keep it"
        danger
        pending={cancelState.status === "pending"}
        onConfirm={async () => {
          const updated = await runCancel();
          setConfirmCancelOpen(false);
          if (updated) onChanged?.(updated);
        }}
        onCancel={() => setConfirmCancelOpen(false)}
      />
    </Card>
  );
}
