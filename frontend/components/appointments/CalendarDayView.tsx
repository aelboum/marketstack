"use client";

// Single-day time grid, reusing the exact hour-grid math the week view
// already proved (`lib/appointments/calendarWeek.ts::GRID_HOURS/
// ROW_HEIGHT_PX/eventLayout/isWithinGridWindow` are per-appointment, not
// week-specific -- CalendarWeekView.tsx itself is left untouched). Real
// data only, via the same `listAppointments()` read path.
import { listAppointments, listCalendars, type Appointment } from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useContactNames } from "@/lib/hooks/useContactNames";
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

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

function formatEventTime(appointment: Appointment): string {
  const start = new Date(appointment.starts_at);
  const end = new Date(appointment.ends_at);
  const fmt = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return `${fmt(start)}–${fmt(end)}`;
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function CalendarDayView({
  tenantId,
  day,
  calendarId,
  onEventClick,
  onNewAppointment,
  reloadKey,
}: {
  tenantId: string;
  day: Date;
  /** Filters to one calendar when set; `null`/omitted shows every calendar. */
  calendarId?: string | null;
  onEventClick: (appointment: Appointment) => void;
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
  const contactInfo = useContactNames(
    tenantId,
    appointments.map((a) => a.contact_id),
  );

  if (appointmentsQuery.status === "loading") {
    return <LoadingState label="Afspraken laden…" />;
  }
  if (appointmentsQuery.status === "error") {
    return <ApiErrorPanel error={appointmentsQuery.error} onRetry={appointmentsQuery.refetch} />;
  }

  const sorted = [...appointments].sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  const inGrid = sorted.filter(isWithinGridWindow);
  const now = new Date();
  const isToday = isSameLocalDay(day, now);
  const nowHour = now.getHours() + now.getMinutes() / 60;
  const showNowLine = isToday && nowHour >= GRID_START_HOUR && nowHour < GRID_END_HOUR;
  const nowTopPx = (nowHour - GRID_START_HOUR) * ROW_HEIGHT_PX;

  if (sorted.length === 0) {
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
              {formatHour(hour)}
            </div>
          ))}
        </div>
        <div className={styles.dayColumn}>
          {showNowLine ? (
            <div className={styles.nowLine} style={{ top: `${nowTopPx}px` }} aria-hidden="true" />
          ) : null}
          {inGrid.map((appointment) => {
            const layout = eventLayout(appointment);
            const name = appointment.contact_id
              ? (contactInfo[appointment.contact_id]?.name ?? "…")
              : "Onbekende klant";
            const where = calendarNames[appointment.calendar_id] ?? "Agenda";
            return (
              <div
                key={appointment.id}
                className={styles.eventPosition}
                style={{ top: `${layout.topPx}px`, height: `${layout.heightPx}px` }}
              >
                <button
                  type="button"
                  className={`${styles.event} ${TONE_CLASS[STATUS_TONE[appointment.status]]}`}
                  onClick={() => onEventClick(appointment)}
                >
                  <span className={styles.eventTitle}>{name}</span>
                  <span className={styles.eventMeta}>
                    {formatEventTime(appointment)} · {where} · {STATUS_LABEL_NL[appointment.status]}
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
