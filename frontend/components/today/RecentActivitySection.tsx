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
import { loadAutomationActivity, loadRecentContacts } from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";

function relativeDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function RecentActivitySection({ tenantId }: { tenantId: string }) {
  const automationQuery = useApiQuery(() => loadAutomationActivity(tenantId), [tenantId]);
  const contactsQuery = useApiQuery(() => loadRecentContacts(tenantId), [tenantId]);

  if (automationQuery.status === "loading" || contactsQuery.status === "loading") {
    return <LoadingState label="Recente activiteit laden…" />;
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
        title="Nog geen recente activiteit"
        description="Zodra er klanten worden toegevoegd of automatiseringen worden uitgevoerd, verschijnt dat hier."
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }} data-testid="recent-activity-list">
      {recentContacts.map((contact) => (
        <Card key={`contact-${contact.id}`}>
          <div style={{ fontSize: "var(--font-size-sm)" }}>
            Nieuw contact:{" "}
            <strong>
              {contact.first_name} {contact.last_name}
            </strong>{" "}
            <span style={{ color: "var(--color-text-faint)" }}>({relativeDay(contact.created_at)})</span>
          </div>
        </Card>
      ))}
      {recentRuns.map((run) => (
        <Card key={`run-${run.id}`}>
          <div style={{ fontSize: "var(--font-size-sm)" }}>
            Automatisering afgerond: <strong>{run.workflowName}</strong>{" "}
            <span style={{ color: "var(--color-text-faint)" }}>
              ({run.completed_at ? relativeDay(run.completed_at) : ""})
            </span>
          </div>
        </Card>
      ))}
    </div>
  );
}
