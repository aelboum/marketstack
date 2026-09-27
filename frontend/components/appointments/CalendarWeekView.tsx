"use client";

// The real week/agenda view (mockup layout parity: design/Calendar.dc.html)
// -- combines `listAppointments()` with `listCalendarEvents()` (Calendar
// Event API, docs/ROADMAP.md Phase 7.5) via
// `lib/appointments/agendaItems.ts::combineAgendaItems()`, the same
// unified `AgendaItem[]` representation Day/Month/Agenda-list already
// consume. Renders both the time-grid and the agenda list markup always;
// which one is visible is decided purely by CSS at the product's one
// canonical breakpoint (CalendarWeekView.module.css), never JS width
// detection -- consistent with this product's existing CSS-only
// responsive convention.
//
// Bucketing reuses `lib/appointments/calendarMonth.ts::groupItemsByDay()`/
// `dayKey()` (already generic over `AgendaItem[]`) rather than
// `calendarWeek.ts::bucketByWeekday()`, which stays `Appointment`-typed
// and untouched -- its own existing tests remain valid unchanged.
// `eventLayout()`/`isWithinGridWindow()` are reused as-is via the same
// `asTimeRange()` shim `CalendarDayView.tsx` already established (they
// only ever read `starts_at`/`ends_at` structurally).
//
// An appointment's title is the contact's real name (resolved via
// `useContactNames`, the same shared hook Conversations' own inbox list
// uses) -- never a fabricated "appointment type" (no such field exists
// on `Appointment`). Its colour comes from the appointment's real
// `status`. A generic event shows its own title and the established
// "Agendapunt" label/outlined treatment (`CalendarDayView.tsx`'s own
// convention). A calendar's name substitutes for the mockup's "where"
// (Amersfoort, Kantoor, …), which has no backing field at all here.
import {
  listAppointments,
  listCalendarEvents,
  listCalendars,
  type Appointment,
} from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useContactNames } from "@/lib/hooks/useContactNames";
import { combineAgendaItems, type AgendaItem } from "@/lib/appointments/agendaItems";
import { dayKey, groupItemsByDay } from "@/lib/appointments/calendarMonth";
import {
  GRID_HOURS,
  STATUS_LABEL_NL,
  STATUS_TONE,
  eventLayout,
  isWithinGridWindow,
  weekDays,
} from "@/lib/appointments/calendarWeek";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import styles from "./CalendarWeekView.module.css";

const APPOINTMENT_SAMPLE_SIZE = 100;

const TONE_CLASS: Record<string, string> = {
  info: styles.toneInfo,
  success: styles.toneSuccess,
  neutral: styles.toneNeutral,
  warning: styles.toneWarning,
};

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

function formatEventTime(item: AgendaItem): string {
  const fmt = (iso: string) => {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };
  return `${fmt(item.startsAt)}–${fmt(item.endsAt)}`;
}

/** `eventLayout()`/`isWithinGridWindow()` (`lib/appointments/calendarWeek.ts`)
 * only ever read `starts_at`/`ends_at` -- structurally compatible with an
 * `AgendaItem`, so this shim (mirrors `CalendarDayView.tsx`'s own)
 * avoids either duplicating that math or widening those functions' own
 * `Appointment`-typed signature just for a shape they never otherwise use. */
function asTimeRange(item: AgendaItem): Appointment {
  return { starts_at: item.startsAt, ends_at: item.endsAt } as Appointment;
}

export function CalendarWeekView({
  tenantId,
  weekStart,
  calendarId,
  isToday,
  onItemClick,
  reloadKey,
}: {
  tenantId: string;
  weekStart: Date;
  /** Filters to one calendar when set; `null`/omitted shows every calendar. */
  calendarId?: string | null;
  /** Which of the 5 rendered days (0=Monday) is today, or `null` when
   * today falls outside the displayed week. */
  isToday: (dayIndex: number) => boolean;
  onItemClick: (item: AgendaItem) => void;
  reloadKey?: unknown;
}) {
  const weekEnd = new Date(weekStart);
  weekEnd.setDate(weekEnd.getDate() + 5); // Monday .. Saturday 00:00, i.e. through Friday.

  const appointmentsQuery = useApiQuery(
    () =>
      listAppointments(tenantId, {
        starts_after: weekStart.toISOString(),
        starts_before: weekEnd.toISOString(),
        limit: APPOINTMENT_SAMPLE_SIZE,
      }).then((page) => page.results),
    [tenantId, weekStart.getTime(), reloadKey],
  );

  const calendarEventsQuery = useApiQuery(
    () =>
      listCalendarEvents(tenantId, {
        starts_after: weekStart.toISOString(),
        starts_before: weekEnd.toISOString(),
        calendar_id: calendarId ?? undefined,
        limit: APPOINTMENT_SAMPLE_SIZE,
      }).then((page) => page.results),
    [tenantId, weekStart.getTime(), calendarId, reloadKey],
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
    return <LoadingState label="Afspraken laden…" />;
  }
  if (appointmentsQuery.status === "error") {
    return <ApiErrorPanel error={appointmentsQuery.error} onRetry={appointmentsQuery.refetch} />;
  }
  if (calendarEventsQuery.status === "error") {
    return <ApiErrorPanel error={calendarEventsQuery.error} onRetry={calendarEventsQuery.refetch} />;
  }

  const items = combineAgendaItems(appointments, calendarEvents);
  const days = weekDays(weekStart);
  const groups = groupItemsByDay(items);
  const buckets = days.map((d) => groups[dayKey(d)] ?? []);
  const dayLabels = days.map((d, i) => ({
    weekday: d.toLocaleDateString("nl-NL", { weekday: "short" }),
    date: d.getDate(),
    full:
      d.toLocaleDateString("nl-NL", { weekday: "long", day: "numeric", month: "long" }) +
      (isToday(i) ? " · Vandaag" : ""),
    today: isToday(i),
  }));

  function itemDisplay(item: AgendaItem) {
    const isAppointment = item.kind === "appointment";
    const name = isAppointment
      ? item.appointment.contact_id
        ? (contactInfo[item.appointment.contact_id]?.name ?? "…")
        : "Onbekende klant"
      : (item.event.title ?? "Evenement");
    const where = isAppointment
      ? (calendarNames[item.appointment.calendar_id] ?? "Agenda")
      : (calendarNames[item.event.calendar_id] ?? "Agenda");
    const statusOrLabel = isAppointment ? STATUS_LABEL_NL[item.appointment.status] : "Agendapunt";
    const tone = isAppointment ? TONE_CLASS[STATUS_TONE[item.appointment.status]] : styles.toneEvent;
    return { name, where, statusOrLabel, tone, isAppointment };
  }

  function EventBlock({ item }: { item: AgendaItem }) {
    const { name, where, statusOrLabel, tone } = itemDisplay(item);
    return (
      <button
        type="button"
        className={`${styles.event} ${tone}`}
        onClick={() => onItemClick(item)}
      >
        <span className={styles.eventTitle}>{name}</span>
        <span className={styles.eventMeta}>
          {formatEventTime(item)} · {where} · {statusOrLabel}
        </span>
      </button>
    );
  }

  return (
    <>
      {/* Time grid -- visible at >=48rem (CalendarWeekView.module.css). */}
      <section aria-label="Weekagenda" className={styles.gridWrapper}>
        <div className={styles.gridHeader}>
          <div />
          {dayLabels.map((d, i) => (
            <div key={i} className={styles.gridHeaderCell}>
              <span className={styles.gridHeaderWeekday}>{d.weekday}</span>
              <span className={styles.gridHeaderDate} data-today={d.today}>
                {d.date}
              </span>
            </div>
          ))}
        </div>
        <div className={styles.gridBody}>
          <div className={styles.hourColumn}>
            {GRID_HOURS.map((hour) => (
              <div key={hour} className={styles.hourLabel}>
                {formatHour(hour)}
              </div>
            ))}
          </div>
          {buckets.map((dayItems, dayIndex) => (
            <div key={dayIndex} className={styles.dayColumn} data-today={dayLabels[dayIndex].today}>
              {dayItems.filter((item) => isWithinGridWindow(asTimeRange(item))).map((item) => {
                const layout = eventLayout(asTimeRange(item));
                return (
                  <div
                    key={item.id}
                    className={styles.eventPosition}
                    style={{ top: `${layout.topPx}px`, height: `${layout.heightPx}px` }}
                  >
                    <EventBlock item={item} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </section>

      {/* Agenda list -- visible at <48rem (CalendarWeekView.module.css). */}
      <div className={styles.agendaWrapper}>
        {dayLabels.map((d, dayIndex) => (
          <section key={dayIndex} className={styles.agendaDay}>
            <h3 className={styles.agendaDayHeading} data-today={d.today}>
              {d.full}
            </h3>
            {buckets[dayIndex].length === 0 ? (
              <p className={styles.agendaEmpty}>Geen afspraken</p>
            ) : (
              <ul className={styles.agendaList}>
                {buckets[dayIndex].map((item) => {
                  const { name, where, statusOrLabel, tone } = itemDisplay(item);
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        className={styles.agendaRow}
                        onClick={() => onItemClick(item)}
                      >
                        <span className={`${styles.agendaTone} ${tone}`} aria-hidden="true" />
                        <span className={styles.agendaTime}>{formatEventTime(item)}</span>
                        <span className={styles.agendaRowBody}>
                          <span className={styles.agendaTitle}>{name}</span>
                          <span className={styles.agendaWhere}>
                            {where} · {statusOrLabel}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        ))}
      </div>
    </>
  );
}
