"use client";

// Calendar resource management -- relocated from the Appointments
// section root (see AppointmentsSubNav.tsx's own comment) to make room
// for the real week view at the root. Logic and components unchanged.
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { AppointmentsSubNav, CalendarsList, CalendarForm } from "@/components/appointments";

export default function CalendarsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Calendars"
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
