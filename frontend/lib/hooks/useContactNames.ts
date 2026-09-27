"use client";

// Shared "resolve contact names/initials for a bounded set of ids"
// hook -- the same pattern `components/conversations/InboxList.tsx` and
// (now) the Appointments week view both need: neither the Conversations
// nor the Appointments API returns a contact name, only `contact_id`, so
// each experience-layer view that lists real records by contact resolves
// names itself via CRM's own `getContact()` -- a handful of explicit
// calls for the ids one page actually shows, never a bulk/CRM-wide
// fetch. A name still resolving shows a neutral placeholder; a lookup
// that fails (deleted contact, no access) shows "Onbekende klant" --
// never the raw `contact_id` (the product-wide "do not expose internal
// IDs" rule).
import { useEffect, useState } from "react";
import { getContact } from "@/lib/api/crm";

export type ContactInfo = { name: string; initials: string };

export function useContactNames(
  tenantId: string,
  contactIds: (string | null)[],
): Record<string, ContactInfo> {
  const [info, setInfo] = useState<Record<string, ContactInfo>>({});

  useEffect(() => {
    const uniqueIds = Array.from(new Set(contactIds.filter((id): id is string => id !== null)));
    const missing = uniqueIds.filter((id) => !(id in info));
    if (missing.length === 0) return;

    let cancelled = false;
    Promise.all(
      missing.map((id) =>
        getContact(tenantId, id)
          .then((contact) => {
            const name = `${contact.first_name} ${contact.last_name}`;
            const initials = `${contact.first_name.charAt(0)}${contact.last_name.charAt(0)}`.toUpperCase();
            return [id, { name, initials }] as const;
          })
          .catch(() => [id, { name: "Onbekende klant", initials: "?" }] as const),
      ),
    ).then((resolved) => {
      if (cancelled) return;
      setInfo((current) => ({ ...current, ...Object.fromEntries(resolved) }));
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, contactIds.join(",")]);

  return info;
}
