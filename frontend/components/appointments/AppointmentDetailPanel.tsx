"use client";

// The read-only-plus-actions view of a single appointment inside the
// Agenda's `SidePanel` (mockup layout parity: design/Calendar.dc.html's
// own `dt-panel` -- clicking an appointment opens this, never the
// centered `Dialog`/`Card` shape `AppointmentCard.tsx` still uses for its
// own, unrelated call sites: booking confirmation and the ID-driven
// "Manage" tab, neither of which this panel replaces).
//
// A deliberate cancel/reschedule/complete/no-show duplication against
// AppointmentCard.tsx, not a refactor of it: those two other call sites
// render inline, standalone, `Card`-wrapped, with no side panel and no
// contact/calendar context to show -- forcing one shared component would
// mean threading a "layout mode" prop through it for no real reuse
// benefit, and risks regressing two working, unrelated surfaces for a
// third one's redesign.
//
// The confirm-before-cancel step is the footer swapping in place
// (mockup: `sel.confirming`), not a second, stacked `ConfirmDialog` --
// the mockup never nests a modal inside the detail panel, and a second
// overlay on top of this one would fight the same Escape-key/backdrop-
// click handling this panel already owns.
import { useState } from "react";
import Link from "next/link";
import {
  cancelAppointment,
  completeAppointment,
  markAppointmentNoShow,
  rescheduleAppointment,
  type Appointment,
  type Calendar,
} from "@/lib/api/appointments";
import { STATUS_LABEL_NL, STATUS_TONE } from "@/lib/appointments/calendarWeek";
import { isoToLocalInput, localInputToIso } from "@/lib/appointments/datetime";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { useContactNames } from "@/lib/hooks/useContactNames";
import { Badge, type BadgeProps } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { SidePanel } from "@/components/ui/SidePanel";
import styles from "./AppointmentDetailPanel.module.css";

const BADGE_TONE: Record<string, BadgeProps["tone"]> = {
  info: "accent",
  success: "success",
  neutral: "neutral",
  warning: "warning",
};

const DOT_COLOR: Record<string, string> = {
  info: "var(--color-accent)",
  success: "var(--color-success)",
  neutral: "var(--color-text-muted)",
  warning: "var(--color-warning)",
};

function formatWhen(startsAt: string, endsAt: string): string {
  const start = new Date(startsAt);
  const end = new Date(endsAt);
  const fmtTime = (d: Date) =>
    `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const dateLabel = start.toLocaleDateString("nl-NL", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const minutes = Math.round((end.getTime() - start.getTime()) / 60_000);
  const duration =
    minutes % 60 === 0
      ? `${minutes / 60} uur`
      : minutes < 60
        ? `${minutes} min`
        : `${Math.floor(minutes / 60)} uur ${minutes % 60} min`;
  return `${dateLabel}\n${fmtTime(start)}–${fmtTime(end)} · ${duration}`;
}

export function AppointmentDetailPanel({
  tenantId,
  appointment,
  calendars,
  onChanged,
  onClose,
}: {
  tenantId: string;
  appointment: Appointment;
  calendars: Calendar[];
  onChanged: (appointment: Appointment) => void;
  onClose: () => void;
}) {
  const [rescheduling, setRescheduling] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [newStart, setNewStart] = useState(isoToLocalInput(appointment.starts_at));
  const [newEnd, setNewEnd] = useState(isoToLocalInput(appointment.ends_at));

  const contactInfo = useContactNames(tenantId, [appointment.contact_id]);

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
  const { run: runComplete, state: completeState } = useAsyncAction(() =>
    completeAppointment(tenantId, appointment.id),
  );
  const { run: runNoShow, state: noShowState } = useAsyncAction(() =>
    markAppointmentNoShow(tenantId, appointment.id),
  );

  const isConfirmed = appointment.status === "confirmed";
  const startIso = localInputToIso(newStart);
  const endIso = localInputToIso(newEnd);
  const rescheduleValid =
    startIso !== null && endIso !== null && new Date(endIso) > new Date(startIso);
  const anyPending =
    cancelState.status === "pending" ||
    rescheduleState.status === "pending" ||
    completeState.status === "pending" ||
    noShowState.status === "pending";

  const calendarName = calendars.find((c) => c.id === appointment.calendar_id)?.name ?? "Agenda";
  const contactId = appointment.contact_id;
  const contact = contactId ? contactInfo[contactId] : undefined;
  const contactName = contactId ? (contact?.name ?? "…") : "Onbekende klant";
  const tone = STATUS_TONE[appointment.status];

  return (
    <SidePanel
      open
      onClose={onClose}
      kicker={
        <>
          <span
            aria-hidden="true"
            className={styles.dot}
            style={{ background: DOT_COLOR[tone] }}
          />
          Afspraak
        </>
      }
      title={contactName}
      tag={<Badge tone={BADGE_TONE[tone]}>{STATUS_LABEL_NL[appointment.status]}</Badge>}
      footer={
        confirmingCancel ? (
          <>
            <span className={styles.confirmQuestion}>Deze afspraak annuleren?</span>
            <Button
              variant="secondary"
              onClick={() => setConfirmingCancel(false)}
              disabled={cancelState.status === "pending"}
            >
              Behouden
            </Button>
            <Button
              variant="danger"
              disabled={cancelState.status === "pending"}
              onClick={async () => {
                const updated = await runCancel();
                setConfirmingCancel(false);
                if (updated) onChanged(updated);
              }}
            >
              {cancelState.status === "pending" ? "Bezig…" : "Ja, annuleren"}
            </Button>
          </>
        ) : (
          <>
            {isConfirmed ? (
              <Button
                variant="danger"
                onClick={() => setConfirmingCancel(true)}
                disabled={anyPending}
              >
                Afspraak annuleren
              </Button>
            ) : null}
            <span className={styles.footerSpacer} />
            {isConfirmed ? (
              <>
                <Button
                  variant="secondary"
                  onClick={() => setRescheduling((v) => !v)}
                  disabled={anyPending}
                >
                  {rescheduling ? "Verzetten annuleren" : "Verzetten"}
                </Button>
                <Button
                  variant="secondary"
                  disabled={anyPending}
                  onClick={async () => {
                    const updated = await runNoShow();
                    if (updated) onChanged(updated);
                  }}
                >
                  {noShowState.status === "pending" ? "Bezig…" : "Niet verschenen"}
                </Button>
                <Button
                  disabled={anyPending}
                  onClick={async () => {
                    const updated = await runComplete();
                    if (updated) onChanged(updated);
                  }}
                >
                  {completeState.status === "pending" ? "Bezig…" : "Markeer als afgerond"}
                </Button>
              </>
            ) : null}
          </>
        )
      }
    >
      <div className={styles.rows}>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Wanneer</span>
          <span className={styles.rowValue}>
            {formatWhen(appointment.starts_at, appointment.ends_at)}
          </span>
        </div>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Agenda</span>
          <span className={styles.rowValue}>{calendarName}</span>
        </div>
      </div>

      {contactId ? (
        <section aria-label="Klant" className={styles.customerSection}>
          <div className={styles.customerHeader}>
            <div className={styles.avatar} aria-hidden="true">
              {contact?.initials ?? "…"}
            </div>
            <div className={styles.customerText}>
              <span className={styles.customerName}>{contactName}</span>
              <span className={styles.customerSub}>Klant</span>
            </div>
          </div>
          <div className={styles.customerActions}>
            <Link href={`/t/${tenantId}/crm/contacts/${contactId}`} className={styles.profileLink}>
              Klantprofiel
            </Link>
          </div>
        </section>
      ) : null}

      {rescheduling && isConfirmed ? (
        <form
          className={styles.rescheduleForm}
          onSubmit={async (event) => {
            event.preventDefault();
            if (!rescheduleValid) return;
            const updated = await runReschedule();
            if (updated) {
              setRescheduling(false);
              onChanged(updated);
            }
          }}
        >
          <Input
            label="Nieuw begin"
            type="datetime-local"
            value={newStart}
            onChange={(event) => setNewStart(event.target.value)}
          />
          <Input
            label="Nieuw einde"
            type="datetime-local"
            value={newEnd}
            onChange={(event) => setNewEnd(event.target.value)}
          />
          <Button type="submit" disabled={rescheduleState.status === "pending" || !rescheduleValid}>
            {rescheduleState.status === "pending" ? "Bezig…" : "Bevestig nieuwe tijd"}
          </Button>
        </form>
      ) : null}

      {rescheduleState.status === "error" ? (
        <InlineNotice tone="danger">
          {rescheduleState.error.status === 409
            ? "Die tijd is niet meer beschikbaar. Kies een ander moment."
            : rescheduleState.error.message}
        </InlineNotice>
      ) : null}
      {cancelState.status === "error" ? (
        <InlineNotice tone="danger">{cancelState.error.message}</InlineNotice>
      ) : null}
      {completeState.status === "error" ? (
        <InlineNotice tone="danger">{completeState.error.message}</InlineNotice>
      ) : null}
      {noShowState.status === "error" ? (
        <InlineNotice tone="danger">{noShowState.error.message}</InlineNotice>
      ) : null}

      {!isConfirmed ? (
        <p className={styles.finalNotice}>
          Dit is de definitieve status van deze afspraak en kan niet meer worden gewijzigd.
        </p>
      ) : null}
    </SidePanel>
  );
}
