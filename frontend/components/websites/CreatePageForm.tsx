"use client";

// Creates a page -- `POST .../websites/{id}/pages`. Starts with empty
// `content_blocks`; block editing happens on the page detail view
// afterward (`ContentBlocksEditor`) -- creating and authoring content in
// one form would conflate two independent actions this backend already
// keeps separate (`create_page()` accepts `content_blocks` but every
// other page-authoring UI in this product edits content after create,
// the same "create first, configure after" shape `CreateWorkflowForm`
// established, adapted here to skip content authoring at creation time
// entirely since a page always starts empty in practice).
import { useState } from "react";
import { createPage, type WebsitePage } from "@/lib/api/websites";
import { MAX_SLUG_LENGTH, MAX_PAGE_TITLE_LENGTH } from "@/lib/websites/constraints";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CreatePageForm({
  tenantId,
  websiteId,
  onSaved,
}: {
  tenantId: string;
  websiteId: string;
  onSaved: (page: WebsitePage) => void;
}) {
  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");

  const { state, run } = useAsyncAction(() => createPage(tenantId, websiteId, { slug, title }));

  const slugTooLong = slug.length > MAX_SLUG_LENGTH;
  const titleTooLong = title.length > MAX_PAGE_TITLE_LENGTH;
  const canSubmit = slug.trim().length > 0 && title.trim().length > 0 && !slugTooLong && !titleTooLong;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const created = await run();
        if (created) onSaved(created);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Slug"
        required
        value={slug}
        onChange={(event) => setSlug(event.target.value)}
        placeholder="home"
        error={slugTooLong ? `Slug must be ${MAX_SLUG_LENGTH} characters or fewer.` : undefined}
      />
      <Input
        label="Title"
        required
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        error={titleTooLong ? `Title must be ${MAX_PAGE_TITLE_LENGTH} characters or fewer.` : undefined}
      />

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Creating…" : "Create page"}
      </Button>
    </form>
  );
}
