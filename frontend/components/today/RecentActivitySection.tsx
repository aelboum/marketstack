"use client";

// "Recently handled" -- the Command Center's cross-domain composition
// (docs/ROADMAP.md Phase 28, section 19's "at least one genuine
// cross-domain composition" requirement): CRM (new contacts) and
// Automation (completed workflow runs) rendered together as one real
// picture of what happened recently, without either domain knowing
// about the other -- this component is the only thing that composes
// them, exactly as docs/ARCHITECTURE.md's module-boundary rule requires
// (a module never depends on another; the experience layer reads both
// through their own published APIs).
//
// Row presentation goes through `components/dashboard/DashboardListRow`
// (mockup layout parity); each row links to the real detail screen for
// that record (a contact, or an automation run) -- both routes exist,
// unlike UpcomingAppointmentsSection's rows.
import { loadAutomationActivity, loadRecentContacts } from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useTranslate } from "@/lib/i18n/locale-context";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { DashboardListRow } from "@/components/dashboard/DashboardListRow";

function relativeDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function initials(firstName: string, lastName: string): string {
  return `${firstName.charAt(0)}${lastName.charAt(0)}`.toUpperCase();
}

export function RecentActivitySection({ tenantId }: { tenantId: string }) {
  const t = useTranslate();
  const automationQuery = useApiQuery(() => loadAutomationActivity(tenantId), [tenantId]);
  const contactsQuery = useApiQuery(() => loadRecentContacts(tenantId), [tenantId]);

  if (automationQuery.status === "loading" || contactsQuery.status === "loading") {
    return <LoadingState label={t("Recente activiteit laden…", "Loading recent activity…")} />;
  }

  if (automationQuery.status === "error") {
    return <ApiErrorPanel error={automationQuery.error} onRetry={automationQuery.refetch} />;
  }
  if (contactsQuery.status === "error") {
    return <ApiErrorPanel error={contactsQuery.error} onRetry={contactsQuery.refetch} />;
  }

  const recentRuns = automationQuery.data.recentlyCompleted.slice(0, 5);
  const recentContacts = contactsQuery.data;

  if (recentRuns.length === 0 && recentContacts.length === 0) {
    return (
      <EmptyState
        title={t("Nog geen recente activiteit", "No recent activity yet")}
        description={t(
          "Zodra er klanten worden toegevoegd of automatiseringen worden uitgevoerd, verschijnt dat hier.",
          "Once customers are added or automations run, it will appear here.",
        )}
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }} data-testid="recent-activity-list">
      {recentContacts.map((contact) => (
        <DashboardListRow
          key={`contact-${contact.id}`}
          href={`/t/${tenantId}/crm/contacts/${contact.id}`}
          lead={initials(contact.first_name, contact.last_name)}
          title={t(
            `Nieuw contact: ${contact.first_name} ${contact.last_name}`,
            `New contact: ${contact.first_name} ${contact.last_name}`,
          )}
          meta={relativeDay(contact.created_at)}
        />
      ))}
      {recentRuns.map((run) => (
        <DashboardListRow
          key={`run-${run.id}`}
          href={`/t/${tenantId}/automation/runs/${run.id}`}
          lead="✓"
          title={t(`Automatisering afgerond: ${run.workflowName}`, `Automation completed: ${run.workflowName}`)}
          meta={run.completed_at ? relativeDay(run.completed_at) : ""}
        />
      ))}
    </div>
  );
}
