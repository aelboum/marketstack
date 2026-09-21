"use client";

// Appointments hub (UI-6, replaces the UI-1 placeholder).
//
// Calendars are the hub, not a list of appointments, because the
// Phase 7 API exposes no authenticated way to list or read appointments
// (see lib/api/appointments.ts's module docstring). Every appointment-
// shaped surface the UI can honestly offer -- booking, and cancel/
// reschedule of an appointment already in hand -- lives under the Book
// and Manage tabs.
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { AppointmentsSubNav, CalendarsList, CalendarForm } from "@/components/appointments";

export default function AppointmentsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Appointments"
        description="Calendars, availability, and booking."
        actions={<Button onClick={() => setCreateOpen(true)}>New calendar</Button>}
      />
      <AppointmentsSubNav tenantId={tenantId} />
      <CalendarsList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            Create a calendar
          </Button>
        }
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New calendar">
        <CalendarForm
          tenantId={tenantId}
          onSaved={() => {
            setCreateOpen(false);
            setReloadKey((key) => key + 1);
          }}
        />
      </Dialog>
    </Page>
  );
}
