"use client";

// Agenda: the business calendar workspace (mockup layout parity for the
// Week view specifically: design/Calendar.dc.html). Day/Week/Month/
// Agenda-list share one real data source (`listAppointments()`,
// docs/ROADMAP.md Phase 28) and one calendar filter. Booking reuses the
// existing, already-correct `BookAppointmentForm` unchanged inside a
// dialog; clicking an event opens the existing `AppointmentCard`
// (cancel/reschedule/complete/no-show) for the appointment already in
// hand -- no separate lookup needed.
//
// Week view itself is untouched (`CalendarWeekView`) -- this file only
// adds the workspace around it (header, toolbar, the other three
// views), per this phase's own "do not rewrite working appointment
// logic unnecessarily."
//
// "+ Nieuw evenement" is a real, disclosed gap, not a fabricated create
// flow: a generic calendar event (`product/appointments
// /calendar_events.py`, Calendar Foundation, docs/ROADMAP.md Phase 7.5)
// has a domain/service layer but no HTTP route yet, so there is nothing
// for this UI to list or POST to. The dialog says so plainly instead of
// pretending to save something. See this phase's own report for the
// exact backend dependency.
import { useRef, useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { cancelAppointment, listCalendars, type Appointment } from "@/lib/api/appointments";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { getWeekStart, isSameDay } from "@/lib/appointments/calendarWeek";
import { addDays, addMonths } from "@/lib/appointments/calendarMonth";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import {
  AppointmentsSubNav,
  BookAppointmentForm,
  AppointmentCard,
  CalendarWeekView,
  CalendarDayView,
  CalendarMonthView,
  CalendarAgendaListView,
} from "@/components/appointments";
import styles from "./page.module.css";

type Toast = { id: string; text: string; appointmentId: string };
type AgendaView = "day" | "week" | "month" | "agenda";

const VIEW_OPTIONS: { key: AgendaView; label: string }[] = [
  { key: "day", label: "Dag" },
  { key: "week", label: "Week" },
  { key: "month", label: "Maand" },
  { key: "agenda", label: "Agenda" },
];

function periodNoun(view: AgendaView): string {
  if (view === "day") return "dag";
  if (view === "week") return "week";
  if (view === "month") return "maand";
  return "periode";
}

function step(date: Date, view: AgendaView, direction: 1 | -1): Date {
  if (view === "day") return addDays(date, direction);
  if (view === "week") return addDays(date, direction * 7);
  if (view === "month") return addMonths(date, direction);
  return addDays(date, direction * 14); // Agenda/list pages its rolling window.
}

export default function AppointmentsWeekPage() {
  const { tenantId } = useTenant();
  const [view, setView] = useState<AgendaView>("week");
  const [cursor, setCursor] = useState(() => new Date());
  const [calendarId, setCalendarId] = useState<string>("all");
  const [bookOpen, setBookOpen] = useState(false);
  const [newEventOpen, setNewEventOpen] = useState(false);
  const [manageAppointment, setManageAppointment] = useState<Appointment | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const toastTimerRef = useRef<number | undefined>(undefined);

  const { run: runUndo } = useAsyncAction(() =>
    cancelAppointment(tenantId, (toast as Toast).appointmentId),
  );

  const calendarsQuery = useApiQuery(() => listCalendars(tenantId, { limit: 100 }), [tenantId]);
  const calendars = calendarsQuery.status === "success" ? calendarsQuery.data.results : [];
  const activeCalendarId = calendarId === "all" ? null : calendarId;

  const today = new Date();
  const weekStart = getWeekStart(cursor);
  const weekEndExclusive = new Date(weekStart);
  weekEndExclusive.setDate(weekEndExclusive.getDate() + 5);
  const weekLabel = `${weekStart.getDate()}–${new Date(weekEndExclusive.getTime() - 86_400_000).toLocaleDateString("nl-NL", { day: "numeric", month: "long", year: "numeric" })}`;

  const periodLabel =
    view === "day"
      ? cursor.toLocaleDateString("nl-NL", {
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        })
      : view === "week"
        ? weekLabel
        : view === "month"
          ? cursor.toLocaleDateString("nl-NL", { month: "long", year: "numeric" })
          : `Vanaf ${cursor.toLocaleDateString("nl-NL", { day: "numeric", month: "long" })}`;

  function isToday(dayIndex: number): boolean {
    const day = new Date(weekStart);
    day.setDate(day.getDate() + dayIndex);
    return isSameDay(day, today);
  }

  function handleBooked(booked: Appointment) {
    setBookOpen(false);
    setReloadKey((key) => key + 1);
    const when = new Date(booked.starts_at).toLocaleString("nl-NL", {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
    setToast({ id: booked.id, appointmentId: booked.id, text: `Ingepland · ${when}` });
    window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 6000);
  }

  return (
    <Page>
      <PageHeader
        title="Agenda"
        description="Afspraken en andere geplande activiteiten op één plek."
        actions={
          <div className={styles.headerActions}>
            <Button variant="secondary" onClick={() => setNewEventOpen(true)}>
              + Nieuw evenement
            </Button>
            <Button onClick={() => setBookOpen(true)}>+ Nieuwe afspraak</Button>
          </div>
        }
      />
      <AppointmentsSubNav tenantId={tenantId} />

      <div className={styles.toolbar}>
        <div className={styles.toolbarStart}>
          <Button variant="secondary" size="sm" onClick={() => setCursor(new Date())}>
            Vandaag
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className={styles.navButton}
            aria-label={`Vorige ${periodNoun(view)}`}
            onClick={() => setCursor((current) => step(current, view, -1))}
          >
            ‹
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className={styles.navButton}
            aria-label={`Volgende ${periodNoun(view)}`}
            onClick={() => setCursor((current) => step(current, view, 1))}
          >
            ›
          </Button>
          <h2 className={styles.periodLabel}>{periodLabel}</h2>
        </div>

        <div className={styles.toolbarEnd}>
          {calendars.length > 0 ? (
            <label className={styles.calendarSelectLabel}>
              <span className="visually-hidden">Agenda</span>
              <select
                className={styles.calendarSelect}
                value={calendarId}
                onChange={(event) => setCalendarId(event.target.value)}
              >
                <option value="all">Alle agenda&apos;s</option>
                {calendars.map((calendar) => (
                  <option key={calendar.id} value={calendar.id}>
                    {calendar.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <div className={styles.viewSwitch} role="group" aria-label="Weergave">
            {VIEW_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                className={styles.viewOption}
                data-active={view === option.key}
                aria-pressed={view === option.key}
                onClick={() => setView(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {view === "week" ? (
        <CalendarWeekView
          tenantId={tenantId}
          weekStart={weekStart}
          isToday={isToday}
          reloadKey={reloadKey}
          onEventClick={setManageAppointment}
        />
      ) : view === "day" ? (
        <CalendarDayView
          tenantId={tenantId}
          day={cursor}
          calendarId={activeCalendarId}
          reloadKey={reloadKey}
          onEventClick={setManageAppointment}
          onNewAppointment={() => setBookOpen(true)}
        />
      ) : view === "month" ? (
        <CalendarMonthView
          tenantId={tenantId}
          monthDate={cursor}
          calendarId={activeCalendarId}
          reloadKey={reloadKey}
          onSelectDay={(date) => {
            setCursor(date);
            setView("day");
          }}
          onNewAppointment={() => setBookOpen(true)}
        />
      ) : (
        <CalendarAgendaListView
          tenantId={tenantId}
          anchorDate={cursor}
          calendarId={activeCalendarId}
          reloadKey={reloadKey}
          onEventClick={setManageAppointment}
          onNewAppointment={() => setBookOpen(true)}
        />
      )}

      <Dialog open={bookOpen} onClose={() => setBookOpen(false)} title="Afspraak inplannen">
        <BookAppointmentForm
          tenantId={tenantId}
          onCancel={() => setBookOpen(false)}
          onBooked={handleBooked}
        />
      </Dialog>

      <Dialog
        open={manageAppointment !== null}
        onClose={() => setManageAppointment(null)}
        title="Afspraak beheren"
      >
        {manageAppointment ? (
          <AppointmentCard
            tenantId={tenantId}
            appointment={manageAppointment}
            onChanged={(updated) => {
              setManageAppointment(updated);
              setReloadKey((key) => key + 1);
            }}
          />
        ) : null}
      </Dialog>

      <Dialog
        open={newEventOpen}
        onClose={() => setNewEventOpen(false)}
        title="Nieuw evenement"
        description="Losse agenda-items die geen afspraak zijn (zoals een interne bespreking of blok) komen in een volgende fase beschikbaar."
      >
        <p className={styles.newEventNotice}>
          Voor nu kun je afspraken met klanten inplannen via <strong>Nieuwe afspraak</strong>.
        </p>
        <div className={styles.newEventActions}>
          <Button variant="secondary" onClick={() => setNewEventOpen(false)}>
            Sluiten
          </Button>
        </div>
      </Dialog>

      {toast ? (
        <div className={styles.toast} role="status">
          <span className={styles.toastText}>{toast.text}</span>
          <button
            type="button"
            className={styles.toastAction}
            onClick={async () => {
              await runUndo();
              setToast(null);
              setReloadKey((key) => key + 1);
            }}
          >
            Ongedaan maken
          </button>
        </div>
      ) : null}
    </Page>
  );
}
