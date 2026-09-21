"use client";

// Calendar detail -- the one appointments surface with a real
// authenticated GET behind it (`GET .../calendars/{id}`).
//
// Delete is offered to everyone and refused by the backend where it
// should be: `event_handlers.py` grants `delete` on
// `appointments.calendar` to the `owner` role only, so a `member` gets
// the same non-enumerating 404 everything else uses. The UI makes no
// client-side role guess (docs/ARCHITECTURE.md §6.1 -- the frontend
// never re-derives an authorization decision).
//
// The delete confirmation warns about a real backend limitation rather
// than hiding it: `calendars.py::delete_calendar()` has no
// appointment-existence guard, so deleting a calendar that still has
// appointments hits the database's own RESTRICT and surfaces as a
// server error, not a clean validation message.
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getCalendar, deleteCalendar } from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import {
  AvailabilityRulesPanel,
  AvailableSlotsPicker,
  BookingLinkPanel,
  CalendarForm,
} from "@/components/appointments";

export default function CalendarDetailPage() {
  const { tenantId, calendarId } = useParams<{ tenantId: string; calendarId: string }>();
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const calendarQuery = useApiQuery(
    () => getCalendar(tenantId, calendarId),
    [tenantId, calendarId],
  );
  // Resolves to `true` only on a real success, so a failed delete (a
  // member without `delete`, or the RESTRICT a calendar with existing
  // appointments hits) keeps the user on this page with the error
  // visible, instead of navigating away from it.
  const { run: runDelete, state: deleteState } = useAsyncAction(async () => {
    await deleteCalendar(tenantId, calendarId);
    return true as const;
  });

  if (calendarQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading calendar…" />
      </Page>
    );
  }
  if (calendarQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={calendarQuery.error} onRetry={calendarQuery.refetch} />
      </Page>
    );
  }

  const calendar = calendarQuery.data;

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/appointments`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to calendars
        </Link>
      </p>
      <PageHeader
        title={calendar.name || "(unnamed calendar)"}
        description={calendar.timezone}
        actions={
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <Button variant="secondary" onClick={() => setEditing((v) => !v)}>
              {editing ? "Close edit" : "Edit"}
            </Button>
            <Button variant="danger" onClick={() => setConfirmDeleteOpen(true)}>
              Delete
            </Button>
          </div>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="calendar-details-heading">
          <h2 id="calendar-details-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Details
          </h2>
          <Card>
            <div
              style={{
                display: "flex",
                gap: "var(--space-2)",
                alignItems: "center",
                marginBottom: "var(--space-3)",
              }}
            >
              <Badge tone="accent">{calendar.timezone}</Badge>
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
              <dt style={{ color: "var(--color-text-muted)" }}>Owner user ID</dt>
              <dd style={{ margin: 0, wordBreak: "break-all" }}>{calendar.owner_user_id}</dd>
              <dt style={{ color: "var(--color-text-muted)" }}>Created</dt>
              <dd style={{ margin: 0 }}>{new Date(calendar.created_at).toLocaleString()}</dd>
              <dt style={{ color: "var(--color-text-muted)" }}>Updated</dt>
              <dd style={{ margin: 0 }}>{new Date(calendar.updated_at).toLocaleString()}</dd>
            </dl>
          </Card>
        </section>

        {editing ? (
          <section aria-labelledby="calendar-edit-heading">
            <h2 id="calendar-edit-heading" style={{ fontSize: "var(--font-size-md)" }}>
              Edit
            </h2>
            <Card>
              <CalendarForm
                tenantId={tenantId}
                calendar={calendar}
                onSaved={() => {
                  setEditing(false);
                  calendarQuery.refetch();
                }}
              />
            </Card>
          </section>
        ) : null}

        <section aria-labelledby="availability-heading">
          <h2 id="availability-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Weekly availability
          </h2>
          <AvailabilityRulesPanel tenantId={tenantId} calendarId={calendar.id} />
        </section>

        <section aria-labelledby="slots-heading">
          <h2 id="slots-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Bookable slots
          </h2>
          <Card>
            <AvailableSlotsPicker
              tenantId={tenantId}
              calendarId={calendar.id}
              timeZone={calendar.timezone}
            />
          </Card>
        </section>

        <section aria-labelledby="booking-link-heading">
          <h2 id="booking-link-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Public booking link
          </h2>
          <Card>
            <BookingLinkPanel tenantId={tenantId} calendarId={calendar.id} />
          </Card>
        </section>
      </div>

      {deleteState.status === "error" ? (
        <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this calendar?"
        description="Its availability rules and public booking link are deleted with it. A calendar that still has appointments cannot be deleted, and the attempt will fail."
        confirmLabel="Delete"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          const deleted = await runDelete();
          setConfirmDeleteOpen(false);
          if (deleted) router.push(`/t/${tenantId}/appointments`);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Page>
  );
}
