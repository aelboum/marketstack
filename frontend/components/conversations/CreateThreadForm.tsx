"use client";

// `contact_id` must be a real, same-tenant CRM contact -- enforced by a
// composite FK server-side (`product/conversations/threads.py::create_thread()`'s
// own docstring). This form fetches the first 100 contacts as a select,
// the same "reference data" convenience UI-3's `OpportunityForm` already
// established -- not an exhaustive contact search.
import { useEffect, useState } from "react";
import { createThread, CHANNELS, type Channel, type Thread } from "@/lib/api/conversations";
import { listContacts } from "@/lib/api/crm";
import type { Contact } from "@/lib/api/crm";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CreateThreadForm({
  tenantId,
  onSaved,
}: {
  tenantId: string;
  onSaved: (thread: Thread) => void;
}) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactId, setContactId] = useState("");
  const [channel, setChannel] = useState<Channel>("email");

  useEffect(() => {
    let cancelled = false;
    listContacts(tenantId, { limit: 100 }).then((page) => {
      if (!cancelled) setContacts(page.results);
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const { state, run } = useAsyncAction(() => createThread(tenantId, { contact_id: contactId, channel }));

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!contactId) return;
        const created = await run();
        if (created) onSaved(created);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Contact</span>
        <select required value={contactId} onChange={(event) => setContactId(event.target.value)}>
          <option value="">Choose…</option>
          {contacts.map((contact) => (
            <option key={contact.id} value={contact.id}>
              {contact.first_name} {contact.last_name}
            </option>
          ))}
        </select>
      </label>

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

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !contactId}>
        {state.status === "pending" ? "Creating…" : "Create conversation"}
      </Button>
    </form>
  );
}
