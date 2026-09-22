"use client";

// Edits a website's `name`/`custom_domain` -- `PATCH .../websites/{id}`.
// `clear_custom_domain` is its own explicit checkbox, never inferred
// from an emptied text field -- the backend needs "omitted" (leave
// unchanged) and "explicit null" (clear it) to be distinguishable
// (`product/websites/routes.py::UpdateWebsiteRequest`'s own module
// docstring), and a blank text input cannot carry that distinction on
// its own.
import { useState } from "react";
import { updateWebsite, type Website } from "@/lib/api/websites";
import { MAX_WEBSITE_NAME_LENGTH, MAX_CUSTOM_DOMAIN_LENGTH } from "@/lib/websites/constraints";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function EditWebsiteForm({
  tenantId,
  website,
  onSaved,
  onCancel,
}: {
  tenantId: string;
  website: Website;
  onSaved: (website: Website) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(website.name);
  const [customDomain, setCustomDomain] = useState(website.custom_domain ?? "");
  const [clearDomain, setClearDomain] = useState(false);

  const { state, run } = useAsyncAction(() => {
    const trimmedDomain = customDomain.trim();
    if (clearDomain) {
      return updateWebsite(tenantId, website.id, { name, clear_custom_domain: true });
    }
    if (trimmedDomain) {
      return updateWebsite(tenantId, website.id, { name, custom_domain: trimmedDomain });
    }
    return updateWebsite(tenantId, website.id, { name });
  });

  const nameTooLong = name.length > MAX_WEBSITE_NAME_LENGTH;
  const domainTooLong = customDomain.length > MAX_CUSTOM_DOMAIN_LENGTH;
  const canSubmit = name.trim().length > 0 && !nameTooLong && !domainTooLong;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const saved = await run();
        if (saved) onSaved(saved);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Name"
        required
        value={name}
        onChange={(event) => setName(event.target.value)}
        error={nameTooLong ? `Name must be ${MAX_WEBSITE_NAME_LENGTH} characters or fewer.` : undefined}
      />
      <Input
        label="Custom domain"
        value={customDomain}
        onChange={(event) => setCustomDomain(event.target.value)}
        disabled={clearDomain}
        placeholder="example.com"
        error={domainTooLong ? `Custom domain must be ${MAX_CUSTOM_DOMAIN_LENGTH} characters or fewer.` : undefined}
      />
      <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
        <input
          type="checkbox"
          checked={clearDomain}
          onChange={(event) => setClearDomain(event.target.checked)}
        />
        Remove the custom domain
      </label>

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
          {state.status === "pending" ? "Saving…" : "Save changes"}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel} disabled={state.status === "pending"}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
