"use client";

import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { AppointmentsSubNav, RemindersPanel } from "@/components/appointments";

export default function RemindersPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader
        title="Reminders"
        description="Send reminders that are due in the next 24 hours."
      />
      <AppointmentsSubNav tenantId={tenantId} />
      <RemindersPanel tenantId={tenantId} />
    </Page>
  );
}
