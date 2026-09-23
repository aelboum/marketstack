"use client";

// Month grid: date navigation and event density only -- deliberately no
// detailed event card per cell (a handful of status-coloured dots plus a
// "+N" overflow count), matching how this phase's own scope draws the
// line for a month view. Selecting a day hands the date back to the
// caller (AppointmentsWeekPage switches to Day view for it), the same
// "click a day to drill in" pattern a business calendar is expected to
// have -- not a second, competing navigation model.
import { listAppointments, listCalendars, type Appointment } from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import {
  addDays,
  dayKey,
  groupItemsByDay,
  monthGridDays,
} from "@/lib/appointments/calendarMonth";
import { appointmentsToAgendaItems } from "@/lib/appointments/agendaItems";
import { STATUS_TONE } from "@/lib/appointments/calendarWeek";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Button } from "@/components/ui/Button";
import styles from "./CalendarMonthView.module.css";

const APPOINTMENT_SAMPLE_SIZE = 300;
const MAX_DOTS_PER_DAY = 3;
const WEEKDAY_LABELS_NL = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"];

const TONE_CLASS: Record<string, string> = {
  info: styles.toneInfo,
  success: styles.toneSuccess,
  neutral: styles.toneNeutral,
  warning: styles.toneWarning,
};

function isSameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function CalendarMonthView({
  tenantId,
  monthDate,
  calendarId,
  onSelectDay,
  onNewAppointment,
  reloadKey,
}: {
  tenantId: string;
  monthDate: Date;
  calendarId?: string | null;
  onSelectDay: (date: Date) => void;
  onNewAppointment: () => void;
  reloadKey?: unknown;
}) {
  const days = monthGridDays(monthDate);
  const gridStart = days[0].date;
  const gridEndExclusive = addDays(days[days.length - 1].date, 1);

  const appointmentsQuery = useApiQuery(
    () =>
      listAppointments(tenantId, {
        starts_after: gridStart.toISOString(),
        starts_before: gridEndExclusive.toISOString(),
        limit: APPOINTMENT_SAMPLE_SIZE,
      }).then((page) => page.results),
    [tenantId, gridStart.getTime(), reloadKey],
  );

  const calendarsQuery = useApiQuery(() => listCalendars(tenantId, { limit: 100 }), [tenantId]);
  const hasMultipleCalendars =
    calendarsQuery.status === "success" && calendarsQuery.data.results.length > 1;

  if (appointmentsQuery.status === "loading") {
    return <LoadingState label="Afspraken laden…" />;
  }
  if (appointmentsQuery.status === "error") {
    return <ApiErrorPanel error={appointmentsQuery.error} onRetry={appointmentsQuery.refetch} />;
  }

  const allAppointments: Appointment[] = appointmentsQuery.data;
  const appointments = calendarId
    ? allAppointments.filter((a) => a.calendar_id === calendarId)
    : allAppointments;
  const groups = groupItemsByDay(appointmentsToAgendaItems(appointments));
  const today = new Date();

  if (appointments.length === 0) {
    return (
      <EmptyState
        title="Geen activiteiten gepland"
        description="Er staat deze maand nog niets in de agenda."
        action={
          <Button size="sm" onClick={onNewAppointment}>
            Nieuwe afspraak
          </Button>
        }
      />
    );
  }

  return (
    <section aria-label="Maandagenda" className={styles.wrapper}>
      <div className={styles.headerRow}>
        {WEEKDAY_LABELS_NL.map((label) => (
          <div key={label} className={styles.headerCell}>
            {label}
          </div>
        ))}
      </div>
      <div className={styles.grid}>
        {days.map(({ date, inMonth }) => {
          const key = dayKey(date);
          const dayItems = groups[key] ?? [];
          const isToday = isSameLocalDay(date, today);
          return (
            <button
              key={key}
              type="button"
              className={styles.cell}
              data-in-month={inMonth}
              data-today={isToday}
              onClick={() => onSelectDay(date)}
              aria-label={date.toLocaleDateString("nl-NL", {
                weekday: "long",
                day: "numeric",
                month: "long",
              })}
            >
              <span className={styles.cellDate} data-today={isToday}>
                {date.getDate()}
              </span>
              {dayItems.length > 0 ? (
                <span className={styles.dots}>
                  {dayItems.slice(0, MAX_DOTS_PER_DAY).map((item) => (
                    <span
                      key={item.id}
                      className={`${styles.dot} ${TONE_CLASS[STATUS_TONE[item.appointment.status]]}`}
                    />
                  ))}
                  {dayItems.length > MAX_DOTS_PER_DAY ? (
                    <span className={styles.dotsOverflow}>+{dayItems.length - MAX_DOTS_PER_DAY}</span>
                  ) : null}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      {hasMultipleCalendars && calendarId ? (
        <p className={styles.filterNote}>Gefilterd op één agenda.</p>
      ) : null}
    </section>
  );
}
