"use client";

// Create and edit share one form -- `POST .../contacts` and
// `PATCH .../contacts/{id}` take the same field set
// (`CreateContactRequest`/`UpdateContactRequest`, `product/crm/routes.py`).
import { useState } from "react";
import { createContact, updateContact, type Contact } from "@/lib/api/crm";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function ContactForm({
  tenantId,
  contact,
  onSaved,
}: {
  tenantId: string;
  /** Omit to create; pass the existing contact to edit it in place. */
  contact?: Contact;
  onSaved: (contact: Contact) => void;
}) {
  const [firstName, setFirstName] = useState(contact?.first_name ?? "");
  const [lastName, setLastName] = useState(contact?.last_name ?? "");
  const [email, setEmail] = useState(contact?.email ?? "");
  const [phone, setPhone] = useState(contact?.phone ?? "");

  const { state, run } = useAsyncAction(() =>
    contact
      ? updateContact(tenantId, contact.id, {
          first_name: firstName,
          last_name: lastName,
          email: email || null,
          phone: phone || null,
        })
      : createContact(tenantId, {
          first_name: firstName,
          last_name: lastName,
          email: email || null,
          phone: phone || null,
        }),
  );

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        const saved = await run();
        if (saved) onSaved(saved);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        <div style={{ flex: 1 }}>
          <Input
            label="First name"
            required
            value={firstName}
            onChange={(event) => setFirstName(event.target.value)}
          />
        </div>
        <div style={{ flex: 1 }}>
          <Input
            label="Last name"
            required
            value={lastName}
            onChange={(event) => setLastName(event.target.value)}
          />
        </div>
      </div>
      <Input
        label="Email"
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Input label="Phone" value={phone} onChange={(event) => setPhone(event.target.value)} />
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !firstName.trim() || !lastName.trim()}>
        {state.status === "pending" ? "Saving…" : contact ? "Save changes" : "Create contact"}
      </Button>
    </form>
  );
}
