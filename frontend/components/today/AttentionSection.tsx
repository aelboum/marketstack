"use client";

// "Needs your attention" -- the Command Center's own top section
// (docs/ROADMAP.md Phase 28, extended by Phase 29 and Phase 30). Real
// data only: failed automation runs (lib/dashboard/commandCenter.ts
// ::loadAutomationActivity()), pending approvals
// (lib/api/approvals.ts::listApprovals()), and conversations awaiting a
// reply (lib/api/conversations.ts::listInbox()) -- no fabricated count,
// no placeholder severity. A tenant with none of these sees an honest
// empty state, not a hidden or invented "0".
//
// **Not a second approval UI** (docs/ROADMAP.md Phase 29's own scope
// limit): this renders one concise summary line and a link into the
// real Approval Inbox (`/t/{tenantId}/approvals`) -- never an
// approve/reject control here.
//
// Row presentation goes through `components/dashboard/DashboardListRow`
// (mockup layout parity) -- the underlying data/hooks below are
// unchanged from before that visual pass.
import { loadAutomationActivity } from "@/lib/dashboard/commandCenter";
import { listApprovals } from "@/lib/api/approvals";
import { listInbox } from "@/lib/api/conversations";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { DashboardListRow } from "@/components/dashboard/DashboardListRow";

function PendingApprovalsLine({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => listApprovals(tenantId, { status: "pending" }), [tenantId]);

  // A dedicated, smaller failure surface here rather than
  // `ApiErrorPanel` replacing this whole section -- a transient failure
  // or permission gap on this one optional sub-query must never hide
  // the automation-failure information this section also shows.
  if (query.status === "error") {
    return null;
  }
  if (query.status === "loading") {
    return null;
  }
  if (query.data.length === 0) {
    return null;
  }

  return (
    <DashboardListRow
      href={`/t/${tenantId}/approvals`}
      lead="!"
      title={`${query.data.length} ${query.data.length === 1 ? "actie wacht" : "acties wachten"} op goedkeuring`}
      tag="Bekijken →"
      tone="warning"
    />
  );
}

function NeedsReplyLine({ tenantId }: { tenantId: string }) {
  // Bounded count, not exhaustive: `listInbox(needs_reply)` scans at most
  // one page of recent threads (product/conversations/inbox.py), the
  // same accepted tradeoff loadAutomationActivity() already makes above.
  const query = useApiQuery(() => listInbox(tenantId, { needs_reply: true }), [tenantId]);

  if (query.status === "error" || query.status === "loading") {
    return null;
  }
  if (query.data.length === 0) {
    return null;
  }

  return (
    <DashboardListRow
      href={`/t/${tenantId}/conversations`}
      lead="@"
      title={`${query.data.length} ${query.data.length === 1 ? "gesprek wacht" : "gesprekken wachten"} op een reactie`}
      tag="Bekijken →"
      tone="warning"
    />
  );
}

export function AttentionSection({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => loadAutomationActivity(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label="Aandachtspunten laden…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const { failed } = query.data;

  if (failed.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column" }}>
        <PendingApprovalsLine tenantId={tenantId} />
        <NeedsReplyLine tenantId={tenantId} />
        <EmptyState
          title="Alles in orde"
          description="Er zijn momenteel geen automatiseringen die mislukt zijn en uw aandacht nodig hebben."
        />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column" }} data-testid="attention-list">
      <PendingApprovalsLine tenantId={tenantId} />
      <NeedsReplyLine tenantId={tenantId} />
      {failed.map((run) => (
        <DashboardListRow
          key={run.id}
          href={`/t/${tenantId}/automation/runs/${run.id}`}
          lead="!"
          title={run.workflowName}
          meta={run.error ?? "Deze automatisering is mislukt."}
          tag="Mislukt"
          tone="danger"
        />
      ))}
    </div>
  );
}
