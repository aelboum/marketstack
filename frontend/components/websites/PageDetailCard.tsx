"use client";

// Page detail: draft editing (title + content blocks, `PATCH .../pages/
// {id}`), publish/unpublish (`POST .../pages/{id}/publish|unpublish`),
// and delete. Editing a draft never touches what is publicly visible --
// only an explicit Publish does (`product/websites/pages.py`'s own
// module docstring) -- so this shows the draft being edited and the
// page's own `status`/`published_at` as separate, honest facts, never
// implying an unsaved edit is already live.
import { useEffect, useState } from "react";
import {
  deletePage,
  publishPage,
  unpublishPage,
  updatePage,
  type ContentBlock,
  type WebsitePage,
  type WebsitePageStatus,
} from "@/lib/api/websites";
import { MAX_PAGE_TITLE_LENGTH } from "@/lib/websites/constraints";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { ContentBlocksEditor } from "./ContentBlocksEditor";

const STATUS_TONE: Record<WebsitePageStatus, "neutral" | "success"> = {
  draft: "neutral",
  published: "success",
};

export function PageDetailCard({
  tenantId,
  page,
  onChanged,
  onDeleted,
}: {
  tenantId: string;
  page: WebsitePage;
  onChanged: (page: WebsitePage) => void;
  onDeleted: () => void;
}) {
  const [title, setTitle] = useState(page.title);
  const [blocks, setBlocks] = useState<ContentBlock[]>(page.content_blocks);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  useEffect(() => {
    setTitle(page.title);
    setBlocks(page.content_blocks);
  }, [page.id, page.title, page.content_blocks]);

  const save = useAsyncAction(() => updatePage(tenantId, page.id, { title, content_blocks: blocks }));
  const publish = useAsyncAction(() => publishPage(tenantId, page.id));
  const unpublish = useAsyncAction(() => unpublishPage(tenantId, page.id));
  const remove = useAsyncAction(() => deletePage(tenantId, page.id));

  const titleTooLong = title.length > MAX_PAGE_TITLE_LENGTH;
  const canSave = title.trim().length > 0 && !titleTooLong;
  const anyPending =
    save.state.status === "pending" ||
    publish.state.status === "pending" ||
    unpublish.state.status === "pending" ||
    remove.state.status === "pending";

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
        <span style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <Badge tone={STATUS_TONE[page.status]}>{page.status}</Badge>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
            slug: {page.slug}
          </span>
        </span>
        <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          {page.status === "draft" ? (
            <Button
              size="sm"
              disabled={anyPending}
              onClick={async () => {
                const updated = await publish.run();
                if (updated) onChanged(updated);
              }}
            >
              {publish.state.status === "pending" ? "Publishing…" : "Publish"}
            </Button>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              disabled={anyPending}
              onClick={async () => {
                const updated = await unpublish.run();
                if (updated) onChanged(updated);
              }}
            >
              {unpublish.state.status === "pending" ? "Unpublishing…" : "Unpublish"}
            </Button>
          )}
          <Button variant="danger" size="sm" disabled={anyPending} onClick={() => setConfirmDeleteOpen(true)}>
            Delete
          </Button>
        </div>
      </div>

      {page.published_at ? (
        <p style={{ margin: "0 0 var(--space-3)", fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
          Last published {new Date(page.published_at).toLocaleString()}
        </p>
      ) : null}

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <Input
          label="Title"
          required
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          error={titleTooLong ? `Title must be ${MAX_PAGE_TITLE_LENGTH} characters or fewer.` : undefined}
        />

        <div>
          <h3 style={{ fontSize: "var(--font-size-sm)", marginBottom: "var(--space-2)" }}>Content blocks</h3>
          <ContentBlocksEditor blocks={blocks} onChange={setBlocks} />
        </div>

        {save.state.status === "error" ? (
          <InlineNotice tone="danger">{save.state.error.message}</InlineNotice>
        ) : null}
        {publish.state.status === "error" ? (
          <InlineNotice tone="danger">{publish.state.error.message}</InlineNotice>
        ) : null}
        {unpublish.state.status === "error" ? (
          <InlineNotice tone="danger">{unpublish.state.error.message}</InlineNotice>
        ) : null}
        {remove.state.status === "error" ? (
          <InlineNotice tone="danger">{remove.state.error.message}</InlineNotice>
        ) : null}

        <Button
          disabled={anyPending || !canSave}
          onClick={async () => {
            const updated = await save.run();
            if (updated) onChanged(updated);
          }}
        >
          {save.state.status === "pending" ? "Saving…" : "Save draft"}
        </Button>
      </div>

      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this page?"
        description="This cannot be undone."
        confirmLabel="Delete page"
        cancelLabel="Keep it"
        danger
        pending={remove.state.status === "pending"}
        onConfirm={async () => {
          await remove.run();
          setConfirmDeleteOpen(false);
          onDeleted();
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Card>
  );
}
