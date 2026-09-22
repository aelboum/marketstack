"use client";

// Approval detail (docs/ROADMAP.md Phase 29). Answers, in business
// language, exactly the questions the phase's own UX spec named: what is
// requested, why, who requested it, when, and its current state --
// nothing here is invented beyond what `control_plane.approval_requests`
// actually stores (`product/approvals/service.py`'s own `ApprovalView`).
//
// **No "affected business object" section**: the real contract's own
// `payload` field is a free-form, tool-specific JSON blob
// (`control_plane/approvals/models.py`) -- safely rendering it in
// business language for an arbitrary, not-yet-known future tool is not
// possible without guessing at its shape, and this phase's own rule is
// "do not invent explanations." A future tool-specific renderer can add
// this once a real tier>=1 tool's payload shape is known; showing
// nothing here is more honest than showing a raw JSON dump.
import { getApproval } from "@/lib/api/approvals";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ApprovalActions } from "./ApprovalActions";

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ApprovalDetail({ tenantId, approvalId }: { tenantId: string; approvalId: string }) {
  const query = useApiQuery(() => getApproval(tenantId, approvalId), [tenantId, approvalId]);

  if (query.status === "loading") {
    return <LoadingState label="Goedkeuring laden…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const approval = query.data;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
      <Card>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          <div>
            <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
              Gevraagde actie
            </div>
            <div style={{ fontSize: "var(--font-size-lg)", fontWeight: "var(--font-weight-medium)" }}>
              {approval.action_label}
            </div>
          </div>

          <div>
            <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
              Waarom is dit nodig?
            </div>
            <div style={{ fontSize: "var(--font-size-sm)" }}>{approval.reason}</div>
          </div>

          <div>
            <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
              Aangevraagd door
            </div>
            {/* The real contract (`core.identity.User`) stores no display
                name or email -- deliberately minimal, per that model's own
                docstring -- so this is the most specific honest answer
                available: a real person in this business, never a raw
                UUID, and never a fabricated name. */}
            <div style={{ fontSize: "var(--font-size-sm)" }}>Een gebruiker in uw organisatie</div>
          </div>

          <div style={{ display: "flex", gap: "var(--space-5)", flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
                Aangevraagd op
              </div>
              <div style={{ fontSize: "var(--font-size-sm)" }}>{formatDateTime(approval.created_at)}</div>
            </div>
            {approval.decided_at ? (
              <div>
                <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
                  Beoordeeld op
                </div>
                <div style={{ fontSize: "var(--font-size-sm)" }}>{formatDateTime(approval.decided_at)}</div>
              </div>
            ) : null}
            <div>
              <div style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
                Status
              </div>
              <Badge tone={approval.status === "rejected" ? "danger" : "neutral"}>
                {approval.status_label}
              </Badge>
            </div>
          </div>
        </div>
      </Card>

      <ApprovalActions tenantId={tenantId} approval={approval} onChanged={query.refetch} />
    </div>
  );
}
