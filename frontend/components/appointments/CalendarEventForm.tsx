"use client";

// Create/edit a generic calendar event -- only the CalendarEvent API's
// own client-settable fields (title, description, starts_at, ends_at,
// and, for a new event, which calendar it belongs to). `calendar_id`
// and `appointment_id` are never edited on an existing event: the API
// itself does not accept them on update
// (`product/appointments/calendar_events.py::update_calendar_event()`'s
// own docstring -- "deliberately not reassignable"), so the calendar
// picker is only shown when creating, not hidden-but-disabled.
import { useState, type FormEvent } from "react";
import {
  createCalendarEvent,
  deleteCalendarEvent,
  updateCalendarEvent,
  type Calendar,
  type CalendarEvent,
} from "@/lib/api/appointments";
import { localInputToIso, isoToLocalInput, toDateInput } from "@/lib/appointments/datetime";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { ConfirmDialog } from "@/components/ui/Dialog";
import styles from "./CalendarEventForm.module.css";

function splitIso(iso: string): { date: string; time: string } {
  const [date, time] = isoToLocalInput(iso).split("T");
  return { date, time };
}

export function CalendarEventForm({
  tenantId,
  calendars,
  event,
  defaultCalendarId,
  defaultDate,
  onCancel,
  onSaved,
  onDeleted,
}: {
  tenantId: string;
  calendars: Calendar[];
  /** Omit to create a new event; pass an existing one to edit it. */
  event?: CalendarEvent;
  defaultCalendarId?: string;
  defaultDate?: Date;
  onCancel: () => void;
  onSaved: (event: CalendarEvent) => void;
  /** Only called for an existing event -- deletion is not offered while
   * creating. Deletes only this `CalendarEvent` row; per the API's own
   * guarantee, never touches an underlying `Appointment` even when this
   * event happens to be appointment-backed. */
  onDeleted?: (eventId: string) => void;
}) {
  const isEdit = event !== undefined;
  const initialStart = event ? splitIso(event.starts_at) : null;
  const initialEnd = event ? splitIso(event.ends_at) : null;
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const [calendarId, setCalendarId] = useState(
    event?.calendar_id ?? defaultCalendarId ?? calendars[0]?.id ?? "",
  );
  const [title, setTitle] = useState(event?.title ?? "");
  const [description, setDescription] = useState(event?.description ?? "");
  const [date, setDate] = useState(initialStart?.date ?? (defaultDate ? toDateInput(defaultDate) : ""));
  const [startTime, setStartTime] = useState(initialStart?.time ?? "09:00");
  const [endTime, setEndTime] = useState(initialEnd?.time ?? "10:00");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [rangeError, setRangeError] = useState<string | null>(null);

  const { state, run } = useAsyncAction(async (startsAtIso: string, endsAtIso: string) => {
    if (event) {
      return updateCalendarEvent(tenantId, event.id, {
        title: title.trim(),
        description: description.trim() ? description.trim() : null,
        starts_at: startsAtIso,
        ends_at: endsAtIso,
      });
    }
    return createCalendarEvent(tenantId, {
      calendar_id: calendarId,
      title: title.trim(),
      description: description.trim() ? description.trim() : null,
      starts_at: startsAtIso,
      ends_at: endsAtIso,
    });
  });

  function handleSubmit(formEvent: FormEvent) {
    formEvent.preventDefault();
    setTitleError(null);
    setRangeError(null);

    if (!title.trim()) {
      setTitleError("Titel is verplicht.");
      return;
    }
    const startsAtIso = date && startTime ? localInputToIso(`${date}T${startTime}`) : null;
    const endsAtIso = date && endTime ? localInputToIso(`${date}T${endTime}`) : null;
    if (!startsAtIso || !endsAtIso) {
      setRangeError("Vul een geldige datum en tijd in.");
      return;
    }
    if (endsAtIso <= startsAtIso) {
      setRangeError("Eindtijd moet na de starttijd liggen.");
      return;
    }

    run(startsAtIso, endsAtIso).then((saved) => {
      if (saved) onSaved(saved);
    });
  }

  const { state: deleteState, run: runDelete } = useAsyncAction(async () => {
    await deleteCalendarEvent(tenantId, (event as CalendarEvent).id);
    return true;
  });

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      {!isEdit ? (
        <label className={styles.field}>
          <span className={styles.label}>Agenda</span>
          <select
            className={styles.select}
            value={calendarId}
            onChange={(changeEvent) => setCalendarId(changeEvent.target.value)}
          >
            {calendars.map((calendar) => (
              <option key={calendar.id} value={calendar.id}>
                {calendar.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <Input
        label="Titel"
        value={title}
        onChange={(changeEvent) => setTitle(changeEvent.target.value)}
        error={titleError ?? undefined}
      />

      <label className={styles.field}>
        <span className={styles.label}>Beschrijving</span>
        <textarea
          className={styles.textarea}
          value={description}
          onChange={(changeEvent) => setDescription(changeEvent.target.value)}
          rows={3}
        />
      </label>

      <div className={styles.row}>
        <Input
          label="Datum"
          type="date"
          value={date}
          onChange={(changeEvent) => setDate(changeEvent.target.value)}
        />
        <Input
          label="Starttijd"
          type="time"
          value={startTime}
          onChange={(changeEvent) => setStartTime(changeEvent.target.value)}
        />
        <Input
          label="Eindtijd"
          type="time"
          value={endTime}
          onChange={(changeEvent) => setEndTime(changeEvent.target.value)}
        />
      </div>

      {rangeError ? <InlineNotice tone="warning">{rangeError}</InlineNotice> : null}
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      {deleteState.status === "error" ? (
        <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice>
      ) : null}

      <div className={styles.actions}>
        {isEdit && onDeleted ? (
          <Button
            type="button"
            variant="danger"
            onClick={() => setConfirmDeleteOpen(true)}
            disabled={state.status === "pending" || deleteState.status === "pending"}
          >
            Verwijderen
          </Button>
        ) : null}
        <Button
          type="button"
          variant="secondary"
          onClick={onCancel}
          disabled={state.status === "pending"}
        >
          Annuleren
        </Button>
        <Button type="submit" disabled={state.status === "pending"}>
          {state.status === "pending" ? "Bezig…" : isEdit ? "Opslaan" : "Aanmaken"}
        </Button>
      </div>

      {isEdit ? (
        <ConfirmDialog
          open={confirmDeleteOpen}
          title="Evenement verwijderen?"
          description="Dit agenda-item wordt permanent verwijderd. Dit kan niet ongedaan worden gemaakt."
          confirmLabel="Verwijderen"
          cancelLabel="Annuleren"
          danger
          pending={deleteState.status === "pending"}
          onConfirm={async () => {
            const deleted = await runDelete();
            setConfirmDeleteOpen(false);
            if (deleted) onDeleted?.((event as CalendarEvent).id);
          }}
          onCancel={() => setConfirmDeleteOpen(false)}
        />
      ) : null}
    </form>
  );
}
