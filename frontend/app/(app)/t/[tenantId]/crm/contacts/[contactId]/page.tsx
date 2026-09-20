"use client";

// Real `GET .../contacts/{id}` exists -- unlike UI-2's client detail
// (no such route in Phase 3), this page fetches the record directly
// rather than finding it inside a list.
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { deleteContact, getContact } from "@/lib/api/crm";
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
import { ContactForm, ActivitiesPanel, TagsPanel, CustomFieldsPanel } from "@/components/crm";

export default function ContactDetailPage() {
  const params = useParams<{ tenantId: string; contactId: string }>();
  const { tenantId, contactId } = params;
  const router = useRouter();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const query = useApiQuery(() => getContact(tenantId, contactId), [tenantId, contactId]);
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteContact(tenantId, contactId));

  if (query.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading contact…" />
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

  const contact = query.data;

  return (
    <Page>
      <PageHeader
        title={`${contact.first_name} ${contact.last_name}`}
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
            <ContactForm tenantId={tenantId} contact={contact} onSaved={query.refetch} />
          </Card>
        </section>

        <section aria-labelledby="tags-heading">
          <h2 id="tags-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Tags
          </h2>
          <Card>
            <TagsPanel tenantId={tenantId} entityType="contact" entityId={contact.id} />
          </Card>
        </section>

        <section aria-labelledby="fields-heading">
          <h2 id="fields-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Custom fields
          </h2>
          <Card>
            <CustomFieldsPanel tenantId={tenantId} entityType="contact" entityId={contact.id} />
          </Card>
        </section>

        <section aria-labelledby="activity-heading">
          <h2 id="activity-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Activity
          </h2>
          <ActivitiesPanel tenantId={tenantId} parent={{ contactId: contact.id }} />
        </section>
      </div>

      {deleteState.status === "error" ? (
        <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this contact?"
        description="This cannot be undone."
        confirmLabel="Delete"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          router.push(`/t/${tenantId}/crm/contacts`);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Page>
  );
}
