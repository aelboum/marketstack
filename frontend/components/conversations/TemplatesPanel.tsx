"use client";

// Message templates (`product/conversations/templates.py`) -- full
// CRUD exists server-side; creating one is owner-only
// (`event_handlers.py::_MEMBER_GRANTS` grants `member` only `read` on
// `conversations.message_template`) -- this panel doesn't pre-check
// that, same non-enumeration discipline as everywhere else.
import { useState } from "react";
import {
  createTemplate,
  deleteTemplate,
  listTemplates,
  updateTemplate,
  CHANNELS,
  type Channel,
  type Template,
} from "@/lib/api/conversations";
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
  const [body, setBody] = useState(template.body);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const { run: runUpdate, state: updateState } = useAsyncAction(() =>
    updateTemplate(tenantId, template.id, { body }),
  );
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteTemplate(tenantId, template.id));

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--space-2)" }}>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <strong>{template.name}</strong>
          {template.channel ? <Badge tone="accent">{template.channel}</Badge> : <Badge>Any channel</Badge>}
        </div>
        <div style={{ display: "flex", gap: "var(--space-1)" }}>
          <Button variant="secondary" size="sm" onClick={() => setEditing((v) => !v)}>
            {editing ? "Cancel" : "Edit"}
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
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={3}
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
        <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
          {template.body}
        </p>
      )}

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
  const [body, setBody] = useState("");
  const [channel, setChannel] = useState<Channel | "">("");
  const { state, run } = useAsyncAction(() =>
    createTemplate(tenantId, { name, body, channel: channel || null }),
  );

  return (
    <Card>
      <h3 style={{ marginTop: 0 }}>Create a template</h3>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim() || !body.trim()) return;
          const created = await run();
          if (created) {
            setName("");
            setBody("");
            onCreated();
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
      >
        <Input label="Name" required value={name} onChange={(event) => setName(event.target.value)} />
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
            Channel (optional -- leave blank for any channel)
          </span>
          <select value={channel} onChange={(event) => setChannel(event.target.value as Channel | "")}>
            <option value="">Any channel</option>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={3}
          placeholder="Template body…"
          style={{ fontFamily: "inherit", fontSize: "var(--font-size-sm)", padding: "var(--space-2)", border: "1px solid var(--color-border-strong)", borderRadius: "var(--radius-sm)" }}
        />
        <Button type="submit" disabled={state.status === "pending" || !name.trim() || !body.trim()}>
          {state.status === "pending" ? "Creating…" : "Create template"}
        </Button>
        {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      </form>
    </Card>
  );
}

export function TemplatesPanel({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => listTemplates(tenantId), [tenantId]);

  if (query.status === "loading") return <LoadingState label="Loading templates…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {query.data.length === 0 ? (
        <EmptyState title="No templates yet" description="Reusable message templates will appear here." />
      ) : (
        query.data.map((template) => (
          <TemplateRow key={template.id} tenantId={tenantId} template={template} onChanged={query.refetch} />
        ))
      )}
      <CreateTemplateForm tenantId={tenantId} onCreated={query.refetch} />
    </div>
  );
}
