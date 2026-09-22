"use client";

// The Unified Inbox list (docs/ROADMAP.md Phase 30) -- a business-
// oriented view over `listInbox()` (`product/conversations/inbox.py`,
// composed server-side within Conversations, joined with a customer name
// here, at the experience layer, per Phase 30's own architecture: this
// component is the ONE place that calls both the Conversations API and
// CRM's own `getContact()` for the bounded set of contacts a page
// actually shows -- neither backend module imports the other.
import { useEffect, useState } from "react";
import {
  listInbox,
  type AssignedFilter,
  type Channel,
  type InboxItem,
} from "@/lib/api/conversations";
import { getContact } from "@/lib/api/crm";
import { inboxTimestamp } from "@/lib/conversations/format";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";

type InboxFilter = "all" | "needs_reply" | "me" | "unassigned";

const FILTER_LABELS: Record<InboxFilter, string> = {
  all: "Alles",
  needs_reply: "Wacht op reactie",
  me: "Toegewezen aan mij",
  unassigned: "Niet toegewezen",
};

const CHANNEL_LABELS: Record<Channel, string> = {
  email: "E-mail",
  sms: "SMS",
  whatsapp: "WhatsApp",
  chat: "Chat",
};

/** Resolves contact names for the bounded set of contacts one page of
 * inbox items actually references -- a handful of explicit `getContact()`
 * calls, never a bulk/CRM-wide fetch. Shows a neutral placeholder while a
 * name is still resolving, never the raw `contact_id` (Phase 30's own
 * "do not expose internal IDs" rule). */
function useContactNames(tenantId: string, contactIds: (string | null)[]): Record<string, string> {
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    const uniqueIds = Array.from(new Set(contactIds.filter((id): id is string => id !== null)));
    const missing = uniqueIds.filter((id) => !(id in names));
    if (missing.length === 0) return;

    let cancelled = false;
    Promise.all(
      missing.map((id) =>
        getContact(tenantId, id)
          .then((contact) => [id, `${contact.first_name} ${contact.last_name}`] as const)
          .catch(() => [id, "Onbekende klant"] as const),
      ),
    ).then((resolved) => {
      if (cancelled) return;
      setNames((current) => ({ ...current, ...Object.fromEntries(resolved) }));
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, contactIds.join(",")]);

  return names;
}

export function InboxList({ tenantId, reloadKey }: { tenantId: string; reloadKey?: unknown }) {
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [channel, setChannel] = useState<Channel | "">("");

  const assigned: AssignedFilter | undefined =
    filter === "me" ? "me" : filter === "unassigned" ? "unassigned" : undefined;
  const needsReply = filter === "needs_reply";

  const query = useApiQuery(
    () =>
      listInbox(tenantId, {
        assigned,
        channel: channel || undefined,
        needs_reply: needsReply || undefined,
      }),
    [tenantId, filter, channel, reloadKey],
  );

  const items = query.status === "success" ? query.data : [];
  const contactNames = useContactNames(
    tenantId,
    items.map((item) => item.contact_id),
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }} role="group" aria-label="Filters">
        {(Object.keys(FILTER_LABELS) as InboxFilter[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            aria-pressed={filter === key}
            style={{
              padding: "var(--space-1) var(--space-3)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--color-border)",
              background: filter === key ? "var(--color-accent-muted)" : "transparent",
              color: filter === key ? "var(--color-accent)" : "var(--color-text-muted)",
              fontSize: "var(--font-size-sm)",
              cursor: "pointer",
            }}
          >
            {FILTER_LABELS[key]}
          </button>
        ))}
        <select
          aria-label="Kanaal"
          value={channel}
          onChange={(event) => setChannel(event.target.value as Channel | "")}
          style={{ fontSize: "var(--font-size-sm)" }}
        >
          <option value="">Alle kanalen</option>
          {(Object.keys(CHANNEL_LABELS) as Channel[]).map((key) => (
            <option key={key} value={key}>
              {CHANNEL_LABELS[key]}
            </option>
          ))}
        </select>
      </div>

      {query.status === "loading" ? <LoadingState label="Inbox laden…" /> : null}
      {query.status === "error" ? (
        <ApiErrorPanel error={query.error} onRetry={query.refetch} />
      ) : null}
      {query.status === "success" && items.length === 0 ? (
        <EmptyState
          title="Niets te zien hier"
          description="Er zijn momenteel geen gesprekken die aan dit filter voldoen."
        />
      ) : null}
      {query.status === "success" && items.length > 0 ? (
        <InboxTable tenantId={tenantId} items={items} contactNames={contactNames} />
      ) : null}
    </div>
  );
}

function InboxTable({
  tenantId,
  items,
  contactNames,
}: {
  tenantId: string;
  items: InboxItem[];
  contactNames: Record<string, string>;
}) {
  const columns: DataTableColumn<InboxItem>[] = [
    {
      key: "contact",
      header: "Klant",
      render: (row) => (
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
          <span>{row.contact_id ? (contactNames[row.contact_id] ?? "…") : "Onbekende klant"}</span>
          {row.needs_reply ? <Badge tone="warning">Wacht op reactie</Badge> : null}
        </div>
      ),
    },
    {
      key: "preview",
      header: "Laatste bericht",
      render: (row) => (
        <span style={{ color: "var(--color-text-muted)" }}>
          {row.last_message_preview ?? "Nog geen berichten"}
        </span>
      ),
    },
    {
      key: "channel",
      header: "Kanaal",
      render: (row) => <Badge tone="accent">{CHANNEL_LABELS[row.channel]}</Badge>,
    },
    {
      key: "time",
      header: "Tijd",
      render: (row) => inboxTimestamp(row.last_message_at ?? row.updated_at),
    },
    {
      key: "assignment",
      header: "Toegewezen",
      render: (row) => (row.assigned_to_user_id ? "Toegewezen" : "Niet toegewezen"),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={items}
      rowKey={(row) => row.thread_id}
      getRowHref={(row) => `/t/${tenantId}/conversations/${row.thread_id}`}
      label="Inbox"
    />
  );
}
