"use client";

// The Approval Inbox (docs/ROADMAP.md Phase 29) -- "Goedkeuringen" in
// the business-oriented navigation. Lists real, pending approval
// requests over the existing SaaS-OS `control_plane.approvals`
// mechanism (`product/approvals/`) -- never a second approval system.
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApprovalsList } from "@/components/approvals";

export default function ApprovalsPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader
        title="Goedkeuringen"
        description="Acties die door het systeem zijn voorgesteld en op uw beoordeling wachten."
      />
      <ApprovalsList tenantId={tenantId} />
    </Page>
  );
}
