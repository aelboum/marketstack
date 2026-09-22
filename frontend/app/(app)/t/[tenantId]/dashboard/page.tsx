"use client";

// "Vandaag" -- the Command Center (docs/ROADMAP.md Phase 28, extended by
// the dashboard-design integration with a KPI strip and a real pipeline
// widget -- visual reference: design/dashboard-design-mockup/). Answers
// "if I have five minutes, what should I do?" using only real data:
// automation activity, today's appointments, recent CRM contacts, and
// now open-pipeline/KPI data, each independently loaded/empty/error-
// stated (components/today/*, components/dashboard/*). No fabricated
// metric, count, or activity anywhere on this page -- the same restraint
// the page already had ("renders no fabricated metrics") now extended
// with real sections instead of a placeholder-free void.
//
// The dashboard-design integration is presentation only: KpiStrip and
// PipelineWidget (components/dashboard/) read through
// lib/dashboard/commandCenter.ts exactly like the existing
// components/today/* sections already do, and DashboardGrid is a plain
// CSS Grid layout wrapper with no data or business logic of its own --
// nothing here forks the app's data/API/shell architecture.
//
// The agency "Clients" (client-business) list and the "Invite teammate"
// flow are real, pre-existing functionality (UI-2) -- kept, not removed,
// per Phase 28's own "do not remove functionality merely to make the
// navigation smaller." The former "Modules" grid (a card per backend
// router, linking to itself) is not kept: it existed only to compensate
// for a navigation that didn't otherwise surface those destinations --
// the new grouped, business-oriented navigation (lib/nav/config.ts) is
// what does that job now, so the grid would only duplicate it.
import { useState } from "react";
import Link from "next/link";
import { useSession } from "@/lib/auth/session-context";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ClientsList, InviteMemberPanel } from "@/components/agency";
import { AttentionSection, UpcomingAppointmentsSection, RecentActivitySection } from "@/components/today";
import { KpiStrip, PipelineWidget, DashboardGrid } from "@/components/dashboard";

export default function DashboardPage() {
  const { user } = useSession();
  const { tenantId } = useTenant();
  const [inviteOpen, setInviteOpen] = useState(false);

  return (
    <Page>
      <PageHeader
        title="Vandaag"
        description={`Ingelogd als ${user?.user_id ?? "—"} · Bedrijf ${tenantId}`}
        actions={<Button onClick={() => setInviteOpen(true)}>Invite teammate</Button>}
      />

      <section aria-labelledby="summary-heading" style={{ marginBottom: "var(--space-5)" }}>
        <h2 id="summary-heading" style={{ fontSize: "var(--font-size-md)" }}>
          Bedrijfsoverzicht
        </h2>
        <KpiStrip tenantId={tenantId} />
      </section>

      <DashboardGrid>
        <section aria-labelledby="upcoming-heading">
          <h2 id="upcoming-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Vandaag op de agenda
          </h2>
          <UpcomingAppointmentsSection tenantId={tenantId} />
        </section>

        <section aria-labelledby="attention-heading">
          <h2 id="attention-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Vraagt uw aandacht
          </h2>
          <AttentionSection tenantId={tenantId} />
        </section>

        <section aria-labelledby="pipeline-heading">
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "var(--space-2)",
            }}
          >
            <h2 id="pipeline-heading" style={{ fontSize: "var(--font-size-md)", margin: 0 }}>
              Pijplijn
            </h2>
            <Link href={`/t/${tenantId}/crm/opportunities`} style={{ fontSize: "var(--font-size-sm)" }}>
              Open verkoop →
            </Link>
          </div>
          <PipelineWidget tenantId={tenantId} />
        </section>

        <section aria-labelledby="recent-heading">
          <h2 id="recent-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Onlangs gebeurd
          </h2>
          <RecentActivitySection tenantId={tenantId} />
        </section>
      </DashboardGrid>

      <section aria-labelledby="clients-heading" style={{ marginTop: "var(--space-5)" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "var(--space-2)",
          }}
        >
          <h2 id="clients-heading" style={{ fontSize: "var(--font-size-md)", margin: 0 }}>
            Klantbedrijven
          </h2>
          <Link href={`/t/${tenantId}/clients`} style={{ fontSize: "var(--font-size-sm)" }}>
            Beheer klantbedrijven →
          </Link>
        </div>
        <ClientsList
          agencyTenantId={tenantId}
          limit={5}
          emptyAction={
            <Link href={`/t/${tenantId}/clients`}>
              <Button size="sm">Create your first client</Button>
            </Link>
          }
        />
      </section>

      <Dialog open={inviteOpen} onClose={() => setInviteOpen(false)} title="Invite a teammate">
        <InviteMemberPanel tenantId={tenantId} />
      </Dialog>
    </Page>
  );
}
