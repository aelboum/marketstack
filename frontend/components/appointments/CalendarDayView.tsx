"use client";

// Single-day time grid, reusing the exact hour-grid math the week view
// already proved (`lib/appointments/calendarWeek.ts::GRID_HOURS/
// ROW_HEIGHT_PX/eventLayout/isWithinGridWindow` are per-item, not
// week-specific -- CalendarWeekView.tsx itself is left untouched). Real
// data only: combines `listAppointments()` with `listCalendarEvents()`
// (Calendar Event API, docs/ROADMAP.md Phase 7.5) via
// `lib/appointments/agendaItems.ts::combineAgendaItems()`, so a generic
// event and an appointment render side by side, visually distinguished.
import {
  listAppointments,
  listCalendarEvents,
  listCalendars,
  type Appointment,
} from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useContactNames } from "@/lib/hooks/useContactNames";
import { combineAgendaItems, type AgendaItem } from "@/lib/appointments/agendaItems";
import {
  GRID_END_HOUR,
  GRID_HOURS,
  GRID_START_HOUR,
  ROW_HEIGHT_PX,
  STATUS_LABEL_NL,
  STATUS_TONE,
  eventLayout,
  isWithinGridWindow,
} from "@/lib/appointments/calendarWeek";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Button } from "@/components/ui/Button";
import styles from "./CalendarDayView.module.css";

const APPOINTMENT_SAMPLE_SIZE = 100;

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

function formatEventTime(item: AgendaItem): string {
  return `${formatTime(item.startsAt)}–${formatTime(item.endsAt)}`;
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** `eventLayout()`/`isWithinGridWindow()` (`lib/appointments/calendarWeek.ts`)
 * only ever read `starts_at`/`ends_at` -- structurally compatible with an
 * `AgendaItem`, so this shim avoids either duplicating that math or
 * widening those functions' own `Appointment`-typed signature just for a
 * shape they never otherwise use. */
function asTimeRange(item: AgendaItem): Appointment {
  return { starts_at: item.startsAt, ends_at: item.endsAt } as Appointment;
}

export function CalendarDayView({
  tenantId,
  day,
  calendarId,
  onItemClick,
  onNewAppointment,
  reloadKey,
}: {
  tenantId: string;
  day: Date;
  /** Filters to one calendar when set; `null`/omitted shows every calendar. */
  calendarId?: string | null;
  onItemClick: (item: AgendaItem) => void;
  onNewAppointment: () => void;
  reloadKey?: unknown;
}) {
  const dayStart = new Date(day.getFullYear(), day.getMonth(), day.getDate());
  const dayEnd = new Date(dayStart);
  dayEnd.setDate(dayEnd.getDate() + 1);

  const appointmentsQuery = useApiQuery(
    () =>
      listAppointments(tenantId, {
        starts_after: dayStart.toISOString(),
        starts_before: dayEnd.toISOString(),
        limit: APPOINTMENT_SAMPLE_SIZE,
      }).then((page) => page.results),
    [tenantId, dayStart.getTime(), reloadKey],
  );

  const calendarEventsQuery = useApiQuery(
    () =>
      listCalendarEvents(tenantId, {
        starts_after: dayStart.toISOString(),
        starts_before: dayEnd.toISOString(),
        calendar_id: calendarId ?? undefined,
        limit: APPOINTMENT_SAMPLE_SIZE,
      }).then((page) => page.results),
    [tenantId, dayStart.getTime(), calendarId, reloadKey],
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
  const inGrid = items.filter((item) => isWithinGridWindow(asTimeRange(item)));
  const now = new Date();
  const isToday = isSameLocalDay(day, now);
  const nowHour = now.getHours() + now.getMinutes() / 60;
  const showNowLine = isToday && nowHour >= GRID_START_HOUR && nowHour < GRID_END_HOUR;
  const nowTopPx = (nowHour - GRID_START_HOUR) * ROW_HEIGHT_PX;

  if (items.length === 0) {
    return (
      <EmptyState
        title="Geen afspraken op deze dag"
        description="Er staat voor deze dag nog niets gepland."
        action={
          <Button size="sm" onClick={onNewAppointment}>
            Nieuwe afspraak
          </Button>
        }
      />
    );
  }

  return (
    <section aria-label="Dagagenda" className={styles.wrapper}>
      <div className={styles.body}>
        <div className={styles.hourColumn}>
          {GRID_HOURS.map((hour) => (
            <div key={hour} className={styles.hourLabel}>
              {`${String(hour).padStart(2, "0")}:00`}
            </div>
          ))}
        </div>
        <div className={styles.dayColumn}>
          {showNowLine ? (
            <div className={styles.nowLine} style={{ top: `${nowTopPx}px` }} aria-hidden="true" />
          ) : null}
          {inGrid.map((item) => {
            const layout = eventLayout(asTimeRange(item));
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
              ? `${formatEventTime(item)} · ${where} · ${STATUS_LABEL_NL[item.appointment.status]}`
              : `${formatEventTime(item)} · ${where} · Agendapunt`;
            const tone = isAppointment ? TONE_CLASS[STATUS_TONE[item.appointment.status]] : styles.toneEvent;
            return (
              <div
                key={item.id}
                className={styles.eventPosition}
                style={{ top: `${layout.topPx}px`, height: `${layout.heightPx}px` }}
              >
                <button
                  type="button"
                  className={`${styles.event} ${tone}`}
                  onClick={() => onItemClick(item)}
                >
                  <span className={styles.eventTitle}>{name}</span>
                  <span className={styles.eventMeta}>{meta}</span>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
