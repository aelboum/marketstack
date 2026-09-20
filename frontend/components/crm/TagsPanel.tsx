"use client";

// Tags attached to one contact/company/opportunity, plus attaching an
// existing tenant tag or creating+attaching a new one
// (`product/crm/tags.py`). Creating a brand-new tag definition
// (`crm.tag:create`) is owner-only server-side (`product/crm
// /event_handlers.py::_MEMBER_GRANTS`) -- this panel does not pre-check
// that (no frontend authorization), it just shows the real 403/404 if a
// non-owner tries.
import { useState } from "react";
import { attachTag, createTag, detachTag, listTags, listTagsForEntity, type EntityType } from "@/lib/api/crm";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function TagsPanel({
  tenantId,
  entityType,
  entityId,
}: {
  tenantId: string;
  entityType: EntityType;
  entityId: string;
}) {
  const [newTagName, setNewTagName] = useState("");
  const attachedQuery = useApiQuery(
    () => listTagsForEntity(tenantId, entityType, entityId),
    [tenantId, entityType, entityId],
  );
  const allTagsQuery = useApiQuery(() => listTags(tenantId), [tenantId]);

  const { run: runDetach } = useAsyncAction((tagId: string) =>
    detachTag(tenantId, entityType, entityId, tagId),
  );
  const { run: runAttachExisting, state: attachState } = useAsyncAction((tagId: string) =>
    attachTag(tenantId, entityType, entityId, tagId),
  );
  const { run: runCreateAndAttach, state: createState } = useAsyncAction(async (name: string) => {
    const tag = await createTag(tenantId, name);
    await attachTag(tenantId, entityType, entityId, tag.id);
    return tag;
  });

  if (attachedQuery.status === "loading") return <LoadingState label="Loading tags…" />;
  if (attachedQuery.status === "error") {
    return <ApiErrorPanel error={attachedQuery.error} onRetry={attachedQuery.refetch} />;
  }

  const attachedIds = new Set(attachedQuery.data.map((t) => t.id));
  const availableToAttach =
    allTagsQuery.status === "success" ? allTagsQuery.data.filter((t) => !attachedIds.has(t.id)) : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-1)" }}>
        {attachedQuery.data.length === 0 ? (
          <span style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-faint)" }}>
            No tags yet.
          </span>
        ) : (
          attachedQuery.data.map((tag) => (
            <Badge key={tag.id} tone="accent">
              {tag.name}{" "}
              <button
                type="button"
                aria-label={`Remove tag ${tag.name}`}
                onClick={async () => {
                  await runDetach(tag.id);
                  attachedQuery.refetch();
                }}
                style={{ background: "none", border: "none", cursor: "pointer", color: "inherit", padding: 0 }}
              >
                ×
              </button>
            </Badge>
          ))
        )}
      </div>

      {availableToAttach.length > 0 ? (
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
            Attach an existing tag
          </span>
          <select
            value=""
            disabled={attachState.status === "pending"}
            onChange={async (event) => {
              const tagId = event.target.value;
              if (!tagId) return;
              await runAttachExisting(tagId);
              attachedQuery.refetch();
            }}
          >
            <option value="">Choose…</option>
            {availableToAttach.map((tag) => (
              <option key={tag.id} value={tag.id}>
                {tag.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!newTagName.trim()) return;
          const created = await runCreateAndAttach(newTagName.trim());
          if (created) {
            setNewTagName("");
            attachedQuery.refetch();
            allTagsQuery.refetch();
          }
        }}
        style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}
      >
        <div style={{ flex: 1 }}>
          <Input
            label="New tag"
            value={newTagName}
            onChange={(event) => setNewTagName(event.target.value)}
            placeholder="e.g. vip"
          />
        </div>
        <Button type="submit" size="sm" disabled={createState.status === "pending" || !newTagName.trim()}>
          Create &amp; attach
        </Button>
      </form>
      {createState.status === "error" ? (
        <InlineNotice tone="danger">{createState.error.message}</InlineNotice>
      ) : null}
    </div>
  );
}
