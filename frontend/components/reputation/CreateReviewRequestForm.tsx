"use client";

// `contact_id` must be a real, same-tenant CRM contact -- enforced by a
// composite FK server-side (`product/reputation/models.py::ReviewRequest`'s
// own module docstring). This form fetches the first 100 contacts as a
// select, the same "reference data" convenience `CreateThreadForm`
// already established -- not an exhaustive contact search.
//
// Channel has exactly one real value (`REQUEST_CHANNELS`), so there is
// nothing to choose -- shown as a fixed label, never a single-option
// select pretending to be a choice.
import { useEffect, useState } from "react";
import { createReviewRequest, type ReviewRequest } from "@/lib/api/reputation";
import { MAX_REQUEST_MESSAGE_LENGTH } from "@/lib/reputation/constraints";
import { listContacts, type Contact } from "@/lib/api/crm";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CreateReviewRequestForm({
  tenantId,
  onSaved,
}: {
  tenantId: string;
  onSaved: (reviewRequest: ReviewRequest) => void;
}) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactId, setContactId] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    listContacts(tenantId, { limit: 100 }).then((page) => {
      if (!cancelled) setContacts(page.results);
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const { state, run } = useAsyncAction(() =>
    createReviewRequest(tenantId, {
      contact_id: contactId,
      message: message.trim() ? message : undefined,
    }),
  );

  const messageTooLong = message.length > MAX_REQUEST_MESSAGE_LENGTH;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!contactId || messageTooLong) return;
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

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Channel: Email
        </span>
      </div>

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Message (optional)
        </span>
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={3}
          aria-label="Message"
          placeholder="A short personal note included in the request…"
          style={{
            fontFamily: "inherit",
            fontSize: "var(--font-size-sm)",
            padding: "var(--space-2)",
            border: `1px solid ${messageTooLong ? "var(--color-danger)" : "var(--color-border-strong)"}`,
            borderRadius: "var(--radius-sm)",
          }}
        />
        {messageTooLong ? (
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-danger)" }} role="alert">
            Message must be {MAX_REQUEST_MESSAGE_LENGTH} characters or fewer.
          </span>
        ) : null}
      </label>

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !contactId || messageTooLong}>
        {state.status === "pending" ? "Sending…" : "Send review request"}
      </Button>
    </form>
  );
}
