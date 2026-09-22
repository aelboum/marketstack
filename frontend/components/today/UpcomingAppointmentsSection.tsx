"use client";

// "Upcoming" -- today's real, booked appointments (docs/ROADMAP.md
// Phase 28), via `product/appointments/`'s own new
// `list_appointments()` read path (this phase's one genuinely-necessary
// backend addition -- no authenticated way to list appointments existed
// before it). Cancelled appointments still show (the caller can tell
// from `status`) -- this is "what's on the calendar today," not a filter
// on top of it.
import { loadTodaysAppointments } from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function UpcomingAppointmentsSection({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => loadTodaysAppointments(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label="Afspraken laden…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const appointments = query.data;

  if (appointments.length === 0) {
    return (
      <EmptyState
        title="Geen afspraken vandaag"
        description="Er zijn momenteel geen afspraken voor vandaag gepland."
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }} data-testid="upcoming-list">
      {appointments.map((appointment) => (
        <Card key={appointment.id}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "var(--space-3)",
            }}
          >
            <strong>{formatTime(appointment.starts_at)}</strong>
            <Badge tone={appointment.status === "cancelled" ? "neutral" : "success"}>
              {appointment.status === "cancelled" ? "Geannuleerd" : "Bevestigd"}
            </Badge>
          </div>
        </Card>
      ))}
    </div>
  );
}
