"use client";

// Creates a website -- `POST .../websites`. `slug` is validated
// server-side against `^[a-z0-9]+(-[a-z0-9]+)*$` after lower-casing
// (`product/websites/slugs.py`'s own module docstring: normalization is
// narrow, never silent rewriting) -- this form only enforces the length
// bound client-side and shows the backend's own message verbatim on a
// real mismatch, the same restraint every other form in this product
// already applies to its own backend-validated fields.
import { useState } from "react";
import { createWebsite, type Website } from "@/lib/api/websites";
import { MAX_SLUG_LENGTH, MAX_WEBSITE_NAME_LENGTH, MAX_CUSTOM_DOMAIN_LENGTH } from "@/lib/websites/constraints";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CreateWebsiteForm({
  tenantId,
  onSaved,
}: {
  tenantId: string;
  onSaved: (website: Website) => void;
}) {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [customDomain, setCustomDomain] = useState("");

  const { state, run } = useAsyncAction(() =>
    createWebsite(tenantId, {
      slug,
      name,
      custom_domain: customDomain.trim() ? customDomain.trim() : undefined,
    }),
  );

  const slugTooLong = slug.length > MAX_SLUG_LENGTH;
  const nameTooLong = name.length > MAX_WEBSITE_NAME_LENGTH;
  const domainTooLong = customDomain.length > MAX_CUSTOM_DOMAIN_LENGTH;
  const canSubmit =
    slug.trim().length > 0 &&
    name.trim().length > 0 &&
    !slugTooLong &&
    !nameTooLong &&
    !domainTooLong;

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
        placeholder="my-site"
        error={slugTooLong ? `Slug must be ${MAX_SLUG_LENGTH} characters or fewer.` : undefined}
      />
      <Input
        label="Name"
        required
        value={name}
        onChange={(event) => setName(event.target.value)}
        error={nameTooLong ? `Name must be ${MAX_WEBSITE_NAME_LENGTH} characters or fewer.` : undefined}
      />
      <Input
        label="Custom domain (optional)"
        value={customDomain}
        onChange={(event) => setCustomDomain(event.target.value)}
        placeholder="example.com"
        error={domainTooLong ? `Custom domain must be ${MAX_CUSTOM_DOMAIN_LENGTH} characters or fewer.` : undefined}
      />

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Creating…" : "Create website"}
      </Button>
    </form>
  );
}
