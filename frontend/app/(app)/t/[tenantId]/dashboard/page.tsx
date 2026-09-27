"use client";

// "Dashboard" -- the Command Center (docs/ROADMAP.md Phase 28, extended by
// the dashboard-design integration -- layout parity with the visual
// reference: design/dashboard-design-mockup/). Answers "if I have five
// minutes, what should I do?" using only real data: automation activity,
// today's appointments, recent CRM contacts, and open-pipeline/KPI data,
// each independently loaded/empty/error-stated (components/today/*,
// components/dashboard/*). No fabricated metric, count, name, or
// activity anywhere on this page.
//
// The dashboard-design integration is presentation only: KpiStrip and
// PipelineWidget (components/dashboard/) read through
// lib/dashboard/commandCenter.ts exactly like the existing
// components/today/* sections already do, and DashboardGrid /
// DashboardWidgetCard are plain layout/chrome wrappers with no data or
// business logic of their own -- nothing here forks the app's data/API/
// shell architecture.
//
// The greeting is deliberately time-of-day only, never a personal name:
// `CurrentUser` (lib/auth/api.ts) carries only `user_id`, no display
// name, so showing one would mean inventing it. The previous "Ingelogd
// als {user_id} · Bedrijf {tenantId}" subtitle is gone for the same
// reason the rest of this product avoids it -- a raw internal id is not
// business language.
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
import { useTenant } from "@/lib/tenant/tenant-context";
import { useTranslate, useLocale } from "@/lib/i18n/locale-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ClientsList, InviteMemberPanel } from "@/components/agency";
import { AttentionSection, UpcomingAppointmentsSection, RecentActivitySection } from "@/components/today";
import { KpiStrip, PipelineWidget, DashboardGrid, DashboardWidgetCard } from "@/components/dashboard";

function greeting(now: Date, t: (nl: string, en: string) => string): string {
  const hour = now.getHours();
  if (hour < 12) return t("Goedemorgen", "Good morning");
  if (hour < 18) return t("Goedemiddag", "Good afternoon");
  return t("Goedenavond", "Good evening");
}

export default function DashboardPage() {
  const { tenantId } = useTenant();
  const { locale } = useLocale();
  const t = useTranslate();
  const [inviteOpen, setInviteOpen] = useState(false);

  const now = new Date();
  const dateLabel = now.toLocaleDateString(locale === "EN" ? "en-US" : "nl-NL", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <Page>
      <PageHeader
        title="Dashboard"
        actions={<Button onClick={() => setInviteOpen(true)}>Invite teammate</Button>}
      />

      <section aria-labelledby="greeting-heading" style={{ marginBottom: "var(--space-5)" }}>
        <h2 id="greeting-heading" style={{ margin: 0, fontSize: "var(--font-size-xl)", letterSpacing: "-0.02em" }}>
          {greeting(now, t)}
        </h2>
        <p style={{ margin: "6px 0 0", fontSize: "var(--font-size-md)", color: "var(--color-text-muted)" }}>
          {t("Dit vraagt vandaag uw aandacht", "Here's what needs your attention today")} · {dateLabel}
        </p>
      </section>

      <section aria-labelledby="summary-heading" style={{ marginBottom: "var(--space-5)" }}>
        <h2
          id="summary-heading"
          style={{ fontSize: "var(--font-size-md)", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--color-text-faint)" }}
        >
          {t("Bedrijfsoverzicht", "Business summary")}
        </h2>
        <KpiStrip tenantId={tenantId} />
      </section>

      <DashboardGrid>
        <DashboardWidgetCard
          eyebrow={t("Vandaag", "Today")}
          title={t("Afspraken", "Appointments")}
          linkHref={`/t/${tenantId}/appointments`}
          linkLabel={t("Open agenda", "Open calendar")}
        >
          <UpcomingAppointmentsSection tenantId={tenantId} />
        </DashboardWidgetCard>

        <DashboardWidgetCard eyebrow={t("Aandacht", "Attention")} title={t("Aandachtspunten", "Needs attention")}>
          <AttentionSection tenantId={tenantId} />
        </DashboardWidgetCard>

        <DashboardWidgetCard
          eyebrow={t("Klanten", "Customers")}
          title={t("Recente activiteit", "Recent activity")}
          linkHref={`/t/${tenantId}/crm`}
          linkLabel={t("Alle klanten", "All customers")}
        >
          <RecentActivitySection tenantId={tenantId} />
        </DashboardWidgetCard>

        <DashboardWidgetCard
          eyebrow={t("Verkoop", "Sales")}
          title={t("Pijplijn", "Pipeline")}
          linkHref={`/t/${tenantId}/crm/opportunities`}
          linkLabel={t("Open verkoop", "Open sales")}
          wide
        >
          <PipelineWidget tenantId={tenantId} />
        </DashboardWidgetCard>
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
