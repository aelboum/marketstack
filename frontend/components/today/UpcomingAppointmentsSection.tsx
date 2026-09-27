"use client";

// "Upcoming" -- today's real, booked appointments (docs/ROADMAP.md
// Phase 28), via `product/appointments/`'s own new
// `list_appointments()` read path (this phase's one genuinely-necessary
// backend addition -- no authenticated way to list appointments existed
// before it). Cancelled appointments still show (the caller can tell
// from `status`) -- this is "what's on the calendar today," not a filter
// on top of it.
//
// Row presentation goes through `components/dashboard/DashboardListRow`
// (mockup layout parity). Rows are deliberately not links: the backend
// exposes no authenticated per-appointment detail endpoint (see
// lib/api/appointments.ts's own module docstring), so there is no real
// destination to link to. The row also cannot show a customer name --
// `Appointment` carries only `contact_id`, no contact name -- showing
// one would mean an extra lookup per row or a fabricated label, neither
// of which this section does.
import { loadTodaysAppointments } from "@/lib/dashboard/commandCenter";
import type { AppointmentStatus } from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useTranslate } from "@/lib/i18n/locale-context";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { DashboardListRow, type DashboardListRowTone } from "@/components/dashboard/DashboardListRow";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

const STATUS_TONE: Record<AppointmentStatus, DashboardListRowTone> = {
  confirmed: "success",
  completed: "success",
  cancelled: "neutral",
  no_show: "danger",
};

export function UpcomingAppointmentsSection({ tenantId }: { tenantId: string }) {
  const t = useTranslate();
  const query = useApiQuery(() => loadTodaysAppointments(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label={t("Afspraken laden…", "Loading appointments…")} />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const appointments = query.data;

  if (appointments.length === 0) {
    return (
      <EmptyState
        title={t("Geen afspraken vandaag", "No appointments today")}
        description={t(
          "Er zijn momenteel geen afspraken voor vandaag gepland.",
          "There are no appointments scheduled for today.",
        )}
      />
    );
  }

  const statusLabel: Record<AppointmentStatus, string> = {
    confirmed: t("Bevestigd", "Confirmed"),
    completed: t("Voltooid", "Completed"),
    cancelled: t("Geannuleerd", "Cancelled"),
    no_show: t("Niet verschenen", "No-show"),
  };

  return (
    <div style={{ display: "flex", flexDirection: "column" }} data-testid="upcoming-list">
      {appointments.map((appointment) => (
        <DashboardListRow
          key={appointment.id}
          lead={formatTime(appointment.starts_at)}
          title={t("Afspraak", "Appointment")}
          meta={`${t("tot", "until")} ${formatTime(appointment.ends_at)}`}
          tag={statusLabel[appointment.status]}
          tone={STATUS_TONE[appointment.status]}
        />
      ))}
    </div>
  );
}
