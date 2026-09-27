// Read-only composition layer for the Inbox's customer panel (mockup
// layout parity: design/Inbox.dc.html). Composes Conversations' own
// `getContact()`-adjacent lookup with CRM (open/most-recent opportunity)
// and Appointments (next upcoming appointment) -- the same "experience
// layer reads each domain through its own published API, no module
// imports another" rule `lib/dashboard/commandCenter.ts` already
// follows. Nothing here fabricates data: a contact with no opportunity
// or no upcoming appointment simply has `null` there, rendered as an
// honest empty state by the caller, never a placeholder value.
import { getContact, listOpportunities, listStages, type Contact } from "@/lib/api/crm";
import { listAppointments, type Appointment } from "@/lib/api/appointments";

// Neither `listOpportunities()` nor `listAppointments()` supports a
// `contact_id` filter (verified against `lib/api/crm.ts`/
// `lib/api/appointments.ts`'s own param types) -- both are composed here
// from one bounded, tenant-wide page, filtered client-side to this one
// contact, the same documented tradeoff `lib/dashboard/commandCenter.ts`
// already makes for its own pipeline summary.
const OPPORTUNITY_SAMPLE_SIZE = 100;
const APPOINTMENT_SAMPLE_SIZE = 50;

export type CustomerPanelOpportunity = {
  id: string;
  name: string;
  stageName: string;
  amount: string | null;
};

export type CustomerPanel = {
  contact: Contact;
  /** The contact's most recently created opportunity, regardless of
   * stage -- `null` when this contact has none. */
  latestOpportunity: CustomerPanelOpportunity | null;
  /** The soonest appointment starting after now for this contact --
   * `null` when none is scheduled. */
  nextAppointment: Appointment | null;
};

export async function loadCustomerPanel(tenantId: string, contactId: string): Promise<CustomerPanel> {
  const [contact, opportunitiesPage, appointmentsPage] = await Promise.all([
    getContact(tenantId, contactId),
    listOpportunities(tenantId, { limit: OPPORTUNITY_SAMPLE_SIZE }),
    listAppointments(tenantId, {
      starts_after: new Date().toISOString(),
      limit: APPOINTMENT_SAMPLE_SIZE,
    }),
  ]);

  const contactOpportunities = opportunitiesPage.results
    .filter((o) => o.contact_id === contactId)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  let latestOpportunity: CustomerPanelOpportunity | null = null;
  const mostRecent = contactOpportunities[0];
  if (mostRecent) {
    const stages = await listStages(tenantId, mostRecent.pipeline_id);
    const stage = stages.find((s) => s.id === mostRecent.stage_id);
    latestOpportunity = {
      id: mostRecent.id,
      name: mostRecent.name,
      stageName: stage?.name ?? "—",
      amount: mostRecent.amount,
    };
  }

  const nextAppointment =
    appointmentsPage.results
      .filter((a) => a.contact_id === contactId)
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at))[0] ?? null;

  return { contact, latestOpportunity, nextAppointment };
}
