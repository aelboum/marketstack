"use client";

// Approval detail (docs/ROADMAP.md Phase 29).
import { useParams } from "next/navigation";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApprovalDetail } from "@/components/approvals";

export default function ApprovalDetailPage() {
  const params = useParams<{ tenantId: string; approvalId: string }>();

  return (
    <Page>
      <PageHeader title="Goedkeuring" />
      <ApprovalDetail tenantId={params.tenantId} approvalId={params.approvalId} />
    </Page>
  );
}
