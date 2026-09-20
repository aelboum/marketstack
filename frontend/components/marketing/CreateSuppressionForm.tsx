"use client";

// Manually create a suppression. `contact_id` is a free-form reference
// on this endpoint (no contact-existence check documented in
// `product/marketing/routes.py`), but typing a raw UUID is not a usable
// UX -- this reuses the CRM contacts list (`lib/api/crm.ts::listContacts`,
// already implemented in UI-3) as a search-to-pick control, the same
// cross-module-via-read-only-API pattern UI-4's `AssignThreadForm`
// established for agency members.
import { useState } from "react";
import { listContacts, type Contact } from "@/lib/api/crm";
import { createSuppression, CHANNELS, SUPPRESSION_REASONS, type Channel, type SuppressionReason } from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CreateSuppressionForm({ tenantId, onSaved }: { tenantId: string; onSaved: () => void }) {
  const [q, setQ] = useState("");
  const [contact, setContact] = useState<Contact | null>(null);
  const [channel, setChannel] = useState<Channel>("email");
  const [reason, setReason] = useState<SuppressionReason>("manual");

  const searchQuery = useApiQuery(
    () => (q.trim() ? listContacts(tenantId, { q, limit: 10 }) : Promise.resolve({ results: [], hasMore: false })),
    [tenantId, q],
  );

  const { state, run } = useAsyncAction(() =>
    createSuppression(tenantId, { contact_id: contact!.id, channel, reason }),
  );

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!contact) return;
        const saved = await run();
        if (saved) {
          setContact(null);
          setQ("");
          onSaved();
        }
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
    >
      {contact ? (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "var(--font-size-sm)" }}>
          <span>
            {contact.first_name} {contact.last_name} ({contact.email ?? "no email"})
          </span>
          <Button type="button" variant="secondary" size="sm" onClick={() => setContact(null)}>
            Change
          </Button>
        </div>
      ) : (
        <>
          <Input
            label="Search contacts"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Name or email…"
          />
          {searchQuery.status === "success" && q.trim() && searchQuery.data.results.length > 0 ? (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)" }}>
              {searchQuery.data.results.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setContact(c)}
                    style={{ width: "100%", textAlign: "left", padding: "var(--space-2)", background: "none", border: "none", cursor: "pointer" }}
                  >
                    {c.first_name} {c.last_name} ({c.email ?? "no email"})
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Channel</span>
        <select value={channel} onChange={(event) => setChannel(event.target.value as Channel)}>
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Reason</span>
        <select value={reason} onChange={(event) => setReason(event.target.value as SuppressionReason)}>
          {SUPPRESSION_REASONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>

      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      <Button type="submit" disabled={state.status === "pending" || !contact}>
        {state.status === "pending" ? "Adding…" : "Add suppression"}
      </Button>
    </form>
  );
}
