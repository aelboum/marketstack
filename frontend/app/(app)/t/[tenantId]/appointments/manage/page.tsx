"use client";

import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { AppointmentsSubNav, ManageAppointmentPanel } from "@/components/appointments";

export default function ManageAppointmentPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader
        title="Manage an appointment"
        description="Cancel or reschedule an appointment by ID."
      />
      <AppointmentsSubNav tenantId={tenantId} />
      <ManageAppointmentPanel tenantId={tenantId} />
    </Page>
  );
}
