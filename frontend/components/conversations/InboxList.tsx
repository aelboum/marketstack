"use client";

// The Unified Inbox list (docs/ROADMAP.md Phase 30, restyled for mockup
// layout parity: design/Inbox.dc.html). A business-oriented view over
// `listInbox()` (`product/conversations/inbox.py`, composed server-side
// within Conversations), joined with a customer name here, at the
// experience layer, per Phase 30's own architecture: this component is
// the ONE place that calls both the Conversations API and CRM's own
// `getContact()` for the bounded set of contacts a page actually shows
// -- neither backend module imports the other.
//
// One bounded, unfiltered fetch (INBOX_SAMPLE_SIZE) backs all three
// filter chips (matches the mockup's own three-chip set: All/Ongelezen/
// Van mij) -- counts and the filtered list are both derived from the
// same loaded set client-side, rather than three separate requests each
// time a chip is picked. "Ongelezen" uses the server's own real
// `needs_reply` flag (a customer's last message has no reply yet) --
// never a client-only "seen it" flag: opening a thread does not itself
// send a reply, so a thread genuinely stays "needs a reply" until one
// is actually sent, which is more accurate than an optimistic
// mark-as-read-on-open would be.
import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  listInbox,
  type Channel,
  type InboxItem,
} from "@/lib/api/conversations";
import { useSession } from "@/lib/auth/session-context";
import { inboxTimestamp } from "@/lib/conversations/format";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useContactNames } from "@/lib/hooks/useContactNames";
import { useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import styles from "./InboxList.module.css";

const INBOX_SAMPLE_SIZE = 100;

const CHANNEL_LABELS: Record<Channel, string> = {
  email: "E-mail",
  sms: "SMS",
  whatsapp: "WhatsApp",
  chat: "Chat",
};

type InboxFilter = "all" | "unread" | "mine";

export function InboxList({ tenantId, reloadKey }: { tenantId: string; reloadKey?: unknown }) {
  const { user } = useSession();
  const pathname = usePathname();
  const [filter, setFilter] = useState<InboxFilter>("all");

  const query = useApiQuery(
    () => listInbox(tenantId, { limit: INBOX_SAMPLE_SIZE }),
    [tenantId, reloadKey],
  );

  const items = query.status === "success" ? query.data : [];
  const contactInfo = useContactNames(
    tenantId,
    items.map((item) => item.contact_id),
  );

  const isMine = (item: InboxItem) => !!user && item.assigned_to_user_id === user.user_id;
  const counts = {
    all: items.length,
    unread: items.filter((item) => item.needs_reply).length,
    mine: items.filter(isMine).length,
  };
  const filtered = items.filter((item) => {
    if (filter === "unread") return item.needs_reply;
    if (filter === "mine") return isMine(item);
    return true;
  });

  return (
    <div className={styles.pane}>
      <div className={styles.filters} role="group" aria-label="Filters">
        {(
          [
            ["all", "Alle", counts.all],
            ["unread", "Ongelezen", counts.unread],
            ["mine", "Van mij", counts.mine],
          ] as const
        ).map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            className={styles.filterChip}
            data-active={filter === key}
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
          >
            {label}
            <span className={styles.filterCount}>{count}</span>
          </button>
        ))}
      </div>

      {query.status === "loading" ? (
        <div className={styles.stateSlot}>
          <LoadingState label="Inbox laden…" />
        </div>
      ) : null}
      {query.status === "error" ? (
        <div className={styles.stateSlot}>
          <ApiErrorPanel error={query.error} onRetry={query.refetch} />
        </div>
      ) : null}
      {query.status === "success" && filtered.length === 0 ? (
        <div className={styles.stateSlot}>
          <EmptyState
            title="Je bent helemaal bij"
            description="Geen gesprekken in deze weergave."
          />
        </div>
      ) : null}
      {query.status === "success" && filtered.length > 0 ? (
        <ul className={styles.list}>
          {filtered.map((item) => {
            const href = `/t/${tenantId}/conversations/${item.thread_id}`;
            const isActive = pathname === href;
            const contact = item.contact_id ? contactInfo[item.contact_id] : undefined;
            const name = contact?.name ?? (item.contact_id ? "…" : "Onbekende klant");
            const initials = contact?.initials ?? "?";
            return (
              <li key={item.thread_id}>
                <Link
                  href={href}
                  className={styles.row}
                  data-active={isActive}
                  aria-current={isActive ? "page" : undefined}
                >
                  <span className={styles.avatar} aria-hidden="true">
                    {initials}
                  </span>
                  <span className={styles.rowBody}>
                    <span className={styles.rowTop}>
                      <span className={styles.rowName} data-unread={item.needs_reply}>
                        {name}
                      </span>
                      <span className={styles.rowTime}>
                        {inboxTimestamp(item.last_message_at ?? item.updated_at)}
                      </span>
                    </span>
                    <span className={styles.rowPreview} data-unread={item.needs_reply}>
                      {item.last_message_preview ?? "Nog geen berichten"}
                    </span>
                    <span className={styles.rowMeta}>
                      {CHANNEL_LABELS[item.channel]}
                      {item.needs_reply ? <span className={styles.unreadTag}>· Ongelezen</span> : null}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
