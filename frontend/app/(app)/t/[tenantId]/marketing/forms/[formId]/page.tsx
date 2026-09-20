"use client";

// Form detail. Read-only: no edit endpoint exists
// (`lib/api/marketing.ts` module docstring). Shows the field
// definitions and the `form_token` needed to build the public submit
// URL -- `POST /v1/marketing/forms/{form_token}/submit` is a public,
// unauthenticated route documented in `product/marketing/routes.py`,
// not one this authenticated app calls itself.
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getForm, deleteForm } from "@/lib/api/marketing";
import { API_BASE_URL } from "@/lib/api/config";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { FormSubmissionsList } from "@/components/marketing/FormSubmissionsList";

export default function FormDetailPage() {
  const { tenantId, formId } = useParams<{ tenantId: string; formId: string }>();
  const router = useRouter();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const formQuery = useApiQuery(() => getForm(tenantId, formId), [tenantId, formId]);
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteForm(tenantId, formId));

  if (formQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading form…" />
      </Page>
    );
  }
  if (formQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={formQuery.error} onRetry={formQuery.refetch} />
      </Page>
    );
  }

  const form = formQuery.data;
  const submitUrl = `${API_BASE_URL}/v1/marketing/forms/${form.form_token}/submit`;

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/marketing/forms`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to forms
        </Link>
      </p>
      <PageHeader
        title={form.name}
        actions={
          <Button variant="danger" onClick={() => setConfirmDeleteOpen(true)}>
            Delete
          </Button>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="details-heading">
          <h2 id="details-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Fields
          </h2>
          <Card>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
              {form.fields.map((field) => (
                <li key={field.name} style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", fontSize: "var(--font-size-sm)" }}>
                  <span>{field.name}</span>
                  <Badge tone="accent">{field.field_type}</Badge>
                  {field.required ? <Badge tone="warning">Required</Badge> : null}
                </li>
              ))}
            </ul>
            <p style={{ marginTop: "var(--space-3)", marginBottom: 0, fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              Public submit endpoint (POST, unauthenticated):
              <br />
              <code style={{ wordBreak: "break-all" }}>{submitUrl}</code>
            </p>
          </Card>
        </section>

        <section aria-labelledby="submissions-heading">
          <h2 id="submissions-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Submissions
          </h2>
          <FormSubmissionsList tenantId={tenantId} formId={form.id} />
        </section>
      </div>

      {deleteState.status === "error" ? <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice> : null}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this form?"
        description="This cannot be undone. Existing submissions are not shown to visitors, but this stops accepting new ones."
        confirmLabel="Delete"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          router.push(`/t/${tenantId}/marketing/forms`);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Page>
  );
}
