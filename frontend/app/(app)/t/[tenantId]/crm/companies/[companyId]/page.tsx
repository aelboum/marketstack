"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { deleteCompany, getCompany } from "@/lib/api/crm";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { CompanyForm, ActivitiesPanel, TagsPanel, CustomFieldsPanel } from "@/components/crm";

export default function CompanyDetailPage() {
  const params = useParams<{ tenantId: string; companyId: string }>();
  const { tenantId, companyId } = params;
  const router = useRouter();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const query = useApiQuery(() => getCompany(tenantId, companyId), [tenantId, companyId]);
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteCompany(tenantId, companyId));

  if (query.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading company…" />
      </Page>
    );
  }
  if (query.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={query.error} onRetry={query.refetch} />
      </Page>
    );
  }

  const company = query.data;

  return (
    <Page>
      <PageHeader
        title={company.name}
        actions={
          <Button variant="danger" onClick={() => setConfirmDeleteOpen(true)}>
            Delete
          </Button>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="details-heading">
          <h2 id="details-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Details
          </h2>
          <Card>
            <CompanyForm tenantId={tenantId} company={company} onSaved={query.refetch} />
          </Card>
        </section>

        <section aria-labelledby="tags-heading">
          <h2 id="tags-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Tags
          </h2>
          <Card>
            <TagsPanel tenantId={tenantId} entityType="company" entityId={company.id} />
          </Card>
        </section>

        <section aria-labelledby="fields-heading">
          <h2 id="fields-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Custom fields
          </h2>
          <Card>
            <CustomFieldsPanel tenantId={tenantId} entityType="company" entityId={company.id} />
          </Card>
        </section>

        <section aria-labelledby="activity-heading">
          <h2 id="activity-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Activity
          </h2>
          <ActivitiesPanel tenantId={tenantId} parent={{ companyId: company.id }} />
        </section>
      </div>

      {deleteState.status === "error" ? (
        <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this company?"
        description="This cannot be undone."
        confirmLabel="Delete"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          router.push(`/t/${tenantId}/crm/companies`);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Page>
  );
}
