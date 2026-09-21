"use client";

// Staff booking flow. The appointment this creates is shown immediately
// afterwards with its cancel/reschedule actions -- not as a convenience,
// but because this is one of only two moments the app ever holds an
// appointment it can act on (there is no list or detail endpoint to get
// back to it later; the id shown on the card is what a staff member
// would need to manage it again).
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import type { Appointment } from "@/lib/api/appointments";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { InlineNotice } from "@/components/ui/InlineNotice";
import {
  AppointmentCard,
  AppointmentsSubNav,
  BookAppointmentForm,
} from "@/components/appointments";

export default function BookAppointmentPage() {
  const { tenantId } = useTenant();
  const [booked, setBooked] = useState<Appointment | null>(null);

  return (
    <Page>
      <PageHeader title="Book an appointment" description="Book on a contact's behalf." />
      <AppointmentsSubNav tenantId={tenantId} />

      {booked ? (
        <section
          aria-labelledby="booked-heading"
          style={{ marginBottom: "var(--space-5)", display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
        >
          <h2 id="booked-heading" style={{ fontSize: "var(--font-size-md)", margin: 0 }}>
            Booked
          </h2>
          <InlineNotice tone="success">
            Appointment booked. Keep the appointment ID below — the API has no way to look an
            appointment up again later.
          </InlineNotice>
          <AppointmentCard tenantId={tenantId} appointment={booked} onChanged={setBooked} />
        </section>
      ) : null}

      <BookAppointmentForm tenantId={tenantId} onBooked={setBooked} />
    </Page>
  );
}
