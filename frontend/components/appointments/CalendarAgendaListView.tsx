"use client";

// Chronological "Vandaag / Morgen / …" list -- a rolling window starting
// at `anchorDate`, real data via `listAppointments()` combined with
// `listCalendarEvents()` (Calendar Event API, docs/ROADMAP.md Phase 7.5).
// Selectable at any breakpoint (unlike CalendarWeekView.tsx's own
// CSS-only mobile agenda fallback, which stays untouched and keeps
// working for the Week view specifically).
import { listAppointments, listCalendarEvents, listCalendars } from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useContactNames } from "@/lib/hooks/useContactNames";
import { addDays, groupItemsByDay } from "@/lib/appointments/calendarMonth";
import { combineAgendaItems, type AgendaItem } from "@/lib/appointments/agendaItems";
import { STATUS_LABEL_NL, STATUS_TONE } from "@/lib/appointments/calendarWeek";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Button } from "@/components/ui/Button";
import styles from "./CalendarAgendaListView.module.css";

const APPOINTMENT_SAMPLE_SIZE = 100;
const WINDOW_DAYS = 14;

const TONE_CLASS: Record<string, string> = {
  info: styles.toneInfo,
  success: styles.toneSuccess,
  neutral: styles.toneNeutral,
  warning: styles.toneWarning,
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function dayHeading(date: Date, today: Date): string {
  if (isSameLocalDay(date, today)) return "Vandaag";
  if (isSameLocalDay(date, addDays(today, 1))) return "Morgen";
  return date.toLocaleDateString("nl-NL", { weekday: "long", day: "numeric", month: "long" });
}

export function CalendarAgendaListView({
  tenantId,
  anchorDate,
  calendarId,
  onItemClick,
  onNewAppointment,
  reloadKey,
}: {
  tenantId: string;
  anchorDate: Date;
  calendarId?: string | null;
  onItemClick: (item: AgendaItem) => void;
  onNewAppointment: () => void;
  reloadKey?: unknown;
}) {
  const windowStart = new Date(
    anchorDate.getFullYear(),
    anchorDate.getMonth(),
    anchorDate.getDate(),
  );
  const windowEnd = addDays(windowStart, WINDOW_DAYS);

  const appointmentsQuery = useApiQuery(
    () =>
      listAppointments(tenantId, {
        starts_after: windowStart.toISOString(),
        starts_before: windowEnd.toISOString(),
        limit: APPOINTMENT_SAMPLE_SIZE,
      }).then((page) => page.results),
    [tenantId, windowStart.getTime(), reloadKey],
  );

  const calendarEventsQuery = useApiQuery(
    () =>
      listCalendarEvents(tenantId, {
        starts_after: windowStart.toISOString(),
        starts_before: windowEnd.toISOString(),
        calendar_id: calendarId ?? undefined,
        limit: APPOINTMENT_SAMPLE_SIZE,
      }).then((page) => page.results),
    [tenantId, windowStart.getTime(), calendarId, reloadKey],
  );

  const calendarsQuery = useApiQuery(() => listCalendars(tenantId, { limit: 100 }), [tenantId]);
  const calendarNames: Record<string, string> = {};
  if (calendarsQuery.status === "success") {
    for (const calendar of calendarsQuery.data.results) {
      calendarNames[calendar.id] = calendar.name || "Agenda";
    }
  }

  const allAppointments = appointmentsQuery.status === "success" ? appointmentsQuery.data : [];
  const appointments = calendarId
    ? allAppointments.filter((a) => a.calendar_id === calendarId)
    : allAppointments;
  const calendarEvents = calendarEventsQuery.status === "success" ? calendarEventsQuery.data : [];
  const contactInfo = useContactNames(
    tenantId,
    appointments.map((a) => a.contact_id),
  );

  if (appointmentsQuery.status === "loading" || calendarEventsQuery.status === "loading") {
    return <LoadingState label="Agenda laden…" />;
  }
  if (appointmentsQuery.status === "error") {
    return <ApiErrorPanel error={appointmentsQuery.error} onRetry={appointmentsQuery.refetch} />;
  }
  if (calendarEventsQuery.status === "error") {
    return <ApiErrorPanel error={calendarEventsQuery.error} onRetry={calendarEventsQuery.refetch} />;
  }

  const items = combineAgendaItems(appointments, calendarEvents);

  if (items.length === 0) {
    return (
      <EmptyState
        title="Geen afspraken gepland"
        description="Er staat de komende twee weken nog niets in de agenda."
        action={
          <Button size="sm" onClick={onNewAppointment}>
            Nieuwe afspraak
          </Button>
        }
      />
    );
  }

  const groups = groupItemsByDay(items);
  const dayKeys = Object.keys(groups).sort();
  const today = new Date();

  return (
    <div className={styles.wrapper}>
      {dayKeys.map((key) => {
        const dayItems = groups[key];
        const date = new Date(dayItems[0].startsAt);
        return (
          <section key={key} className={styles.day}>
            <h3 className={styles.dayHeading}>{dayHeading(date, today)}</h3>
            <ul className={styles.list}>
              {dayItems.map((item) => {
                const isAppointment = item.kind === "appointment";
                const name = isAppointment
                  ? item.appointment.contact_id
                    ? (contactInfo[item.appointment.contact_id]?.name ?? "…")
                    : "Onbekende klant"
                  : (item.event.title ?? "Evenement");
                const where = isAppointment
                  ? (calendarNames[item.appointment.calendar_id] ?? "Agenda")
                  : (calendarNames[item.event.calendar_id] ?? "Agenda");
                const meta = isAppointment
                  ? `${where} · ${STATUS_LABEL_NL[item.appointment.status]}`
                  : `${where} · Agendapunt`;
                const tone = isAppointment
                  ? TONE_CLASS[STATUS_TONE[item.appointment.status]]
                  : styles.toneEvent;
                return (
                  <li key={item.id}>
                    <button type="button" className={styles.row} onClick={() => onItemClick(item)}>
                      <span className={styles.time}>{formatTime(item.startsAt)}</span>
                      <span className={`${styles.tone} ${tone}`} aria-hidden="true" />
                      <span className={styles.rowBody}>
                        <span className={styles.title}>{name}</span>
                        <span className={styles.meta}>{meta}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
