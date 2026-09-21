"use client";

// Marketing templates -- full CRUD plus clone
// (`product/marketing/routes.py`'s own `/templates/{id}/clone`), unlike
// UI-4's conversations templates which have no clone route. Mirrors
// `components/conversations/TemplatesPanel.tsx`'s row/create-form shape.
import { useState } from "react";
import {
  createTemplate,
  deleteTemplate,
  listTemplates,
  updateTemplate,
  cloneTemplate,
  TEMPLATE_TYPES,
  type TemplateType,
  type Template,
} from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

function TemplateRow({
  tenantId,
  template,
  onChanged,
}: {
  tenantId: string;
  template: Template;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(template.content);
  const [cloning, setCloning] = useState(false);
  const [cloneName, setCloneName] = useState(`${template.name} copy`);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const { run: runUpdate, state: updateState } = useAsyncAction(() =>
    updateTemplate(tenantId, template.id, { content }),
  );
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteTemplate(tenantId, template.id));
  const { run: runClone, state: cloneState } = useAsyncAction(() => cloneTemplate(tenantId, template.id, cloneName));

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--space-2)" }}>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <h2 style={{ margin: 0, fontSize: "var(--font-size-md)" }}>{template.name}</h2>
          <Badge tone="accent">{template.template_type}</Badge>
        </div>
        <div style={{ display: "flex", gap: "var(--space-1)" }}>
          <Button variant="secondary" size="sm" onClick={() => setEditing((v) => !v)}>
            {editing ? "Cancel" : "Edit"}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setCloning((v) => !v)}>
            {cloning ? "Cancel clone" : "Clone"}
          </Button>
          <Button variant="danger" size="sm" onClick={() => setConfirmDeleteOpen(true)}>
            Delete
          </Button>
        </div>
      </div>

      {editing ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            const saved = await runUpdate();
            if (saved) {
              setEditing(false);
              onChanged();
            }
          }}
          style={{ marginTop: "var(--space-2)", display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
        >
          <textarea
            aria-label={`Content of template ${template.name}`}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            rows={4}
            style={{ fontFamily: "inherit", fontSize: "var(--font-size-sm)", padding: "var(--space-2)", border: "1px solid var(--color-border-strong)", borderRadius: "var(--radius-sm)" }}
          />
          <Button type="submit" size="sm" disabled={updateState.status === "pending"}>
            Save
          </Button>
          {updateState.status === "error" ? (
            <InlineNotice tone="danger">{updateState.error.message}</InlineNotice>
          ) : null}
        </form>
      ) : (
        <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)", whiteSpace: "pre-wrap" }}>
          {template.content}
        </p>
      )}

      {cloning ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (!cloneName.trim()) return;
            const cloned = await runClone();
            if (cloned) {
              setCloning(false);
              onChanged();
            }
          }}
          style={{ marginTop: "var(--space-2)", display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}
        >
          <Input label="New template name" value={cloneName} onChange={(event) => setCloneName(event.target.value)} />
          <Button type="submit" size="sm" disabled={cloneState.status === "pending" || !cloneName.trim()}>
            Clone
          </Button>
        </form>
      ) : null}
      {cloneState.status === "error" ? <InlineNotice tone="danger">{cloneState.error.message}</InlineNotice> : null}

      {deleteState.status === "error" ? (
        <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this template?"
        description="This cannot be undone."
        confirmLabel="Delete"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          setConfirmDeleteOpen(false);
          onChanged();
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Card>
  );
}

function CreateTemplateForm({ tenantId, onCreated }: { tenantId: string; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [templateType, setTemplateType] = useState<TemplateType>("email_campaign");
  const [content, setContent] = useState("");
  const { state, run } = useAsyncAction(() =>
    createTemplate(tenantId, { name, template_type: templateType, content }),
  );

  return (
    <Card>
      <h2 style={{ marginTop: 0, fontSize: "var(--font-size-md)" }}>Create a template</h2>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim() || !content.trim()) return;
          const created = await run();
          if (created) {
            setName("");
            setContent("");
            onCreated();
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
      >
        <Input label="Name" required value={name} onChange={(event) => setName(event.target.value)} />
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Type</span>
          <select value={templateType} onChange={(event) => setTemplateType(event.target.value as TemplateType)}>
            {TEMPLATE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          rows={4}
          aria-label="Template content"
          placeholder="Template content…"
          style={{ fontFamily: "inherit", fontSize: "var(--font-size-sm)", padding: "var(--space-2)", border: "1px solid var(--color-border-strong)", borderRadius: "var(--radius-sm)" }}
        />
        <Button type="submit" disabled={state.status === "pending" || !name.trim() || !content.trim()}>
          {state.status === "pending" ? "Creating…" : "Create template"}
        </Button>
        {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      </form>
    </Card>
  );
}

export function TemplatesPanel({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => listTemplates(tenantId, { limit: 100 }), [tenantId]);

  if (query.status === "loading") return <LoadingState label="Loading templates…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {query.data.results.length === 0 ? (
        <EmptyState title="No templates yet" description="Reusable campaign templates will appear here." />
      ) : (
        query.data.results.map((template) => (
          <TemplateRow key={template.id} tenantId={tenantId} template={template} onChanged={query.refetch} />
        ))
      )}
      <CreateTemplateForm tenantId={tenantId} onCreated={query.refetch} />
    </div>
  );
}
