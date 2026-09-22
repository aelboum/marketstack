"use client";

// The website's own top-level fields, an inline edit toggle, and delete
// (with confirmation -- deleting a website cascades to every one of its
// pages, `product/websites/models.py::Page.website_id`'s own `ON DELETE
// CASCADE`). Delete is offered to everyone the same way Cancel/Delete
// buttons are offered elsewhere in this product -- the backend's own
// owner-only restriction (`product/websites/event_handlers.py`'s own
// module docstring) is enforced there, not re-derived here.
import { useState } from "react";
import { deleteWebsite, type Website } from "@/lib/api/websites";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { EditWebsiteForm } from "./EditWebsiteForm";

export function WebsiteDetailCard({
  tenantId,
  website,
  onChanged,
  onDeleted,
}: {
  tenantId: string;
  website: Website;
  onChanged: (website: Website) => void;
  onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { run: runDelete, state } = useAsyncAction(() => deleteWebsite(tenantId, website.id));

  if (editing) {
    return (
      <Card>
        <EditWebsiteForm
          tenantId={tenantId}
          website={website}
          onSaved={(updated) => {
            setEditing(false);
            onChanged(updated);
          }}
          onCancel={() => setEditing(false)}
        />
      </Card>
    );
  }

  return (
    <Card>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "var(--space-2)",
          flexWrap: "wrap",
          marginBottom: "var(--space-3)",
        }}
      >
        <strong>{website.name}</strong>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button variant="danger" size="sm" onClick={() => setConfirmOpen(true)}>
            Delete
          </Button>
        </div>
      </div>

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "var(--space-1) var(--space-3)",
          margin: 0,
          fontSize: "var(--font-size-sm)",
        }}
      >
        <dt style={{ color: "var(--color-text-muted)" }}>Slug</dt>
        <dd style={{ margin: 0 }}>{website.slug}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Custom domain</dt>
        <dd style={{ margin: 0 }}>
          {website.custom_domain ?? <Badge tone="neutral">None</Badge>}
        </dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Created</dt>
        <dd style={{ margin: 0 }}>{new Date(website.created_at).toLocaleString()}</dd>
      </dl>

      {state.status === "error" ? (
        <div style={{ marginTop: "var(--space-3)" }}>
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="Delete this website?"
        description="Every page on this website is deleted too. This cannot be undone."
        confirmLabel="Delete website"
        cancelLabel="Keep it"
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          setConfirmOpen(false);
          onDeleted();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </Card>
  );
}
