"use client";

// Cancel or reschedule an appointment by its id.
//
// This exists in this shape because of a real, documented backend gap,
// not a design preference: the Phase 7 API has `POST .../appointments/
// {id}/cancel` and `.../reschedule`, but **no authenticated way to list
// or read an appointment**. So there is nothing to browse and nothing to
// pre-load -- a staff member arrives holding an id (from the booking
// they just made, from an audit record, or from support), and these are
// the only two operations the backend will then perform.
//
// The id is not looked up before acting, because no lookup endpoint
// exists. The first real feedback is the response to the cancel or
// reschedule itself: an unknown id, an id in another tenant, and an id
// the actor may not touch all come back as the same non-enumerating 404
// -- deliberately indistinguishable, and shown as such.
//
// This mirrors UI-4's AssignThreadForm, which is a raw user-id input for
// the same underlying reason (no "list tenant members" endpoint).
import { useState } from "react";
import { cancelAppointment, type Appointment } from "@/lib/api/appointments";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { AppointmentCard } from "./AppointmentCard";

export function ManageAppointmentPanel({ tenantId }: { tenantId: string }) {
  const [appointmentId, setAppointmentId] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<Appointment | null>(null);

  const { run, state } = useAsyncAction(() => cancelAppointment(tenantId, appointmentId.trim()));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <Card>
        <p style={{ marginTop: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
          The Appointments API has no endpoint for listing or reading appointments, so there is no
          appointment list to browse. Enter an appointment ID to cancel it. Cancelling is the only
          action reachable from an ID alone — rescheduling is offered on the result below, and on an
          appointment you have just booked.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!appointmentId.trim()) return;
            setConfirmOpen(true);
          }}
          style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}
        >
          <div style={{ flex: 1, minWidth: 260 }}>
            <Input
              label="Appointment ID"
              value={appointmentId}
              onChange={(event) => setAppointmentId(event.target.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
            />
          </div>
          <Button type="submit" variant="danger" disabled={!appointmentId.trim()}>
            Cancel appointment
          </Button>
        </form>

        {state.status === "error" ? (
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        ) : null}
      </Card>

      {result ? (
        <section aria-labelledby="manage-result-heading">
          <h2 id="manage-result-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Result
          </h2>
          <AppointmentCard tenantId={tenantId} appointment={result} onChanged={setResult} />
        </section>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="Cancel this appointment?"
        description="The contact's booking is cancelled and the slot becomes bookable again. This cannot be undone."
        confirmLabel="Cancel appointment"
        cancelLabel="Keep it"
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          const cancelled = await run();
          setConfirmOpen(false);
          if (cancelled) setResult(cancelled);
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
