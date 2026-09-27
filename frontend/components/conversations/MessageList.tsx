"use client";

// Message history for one thread (mockup layout parity: design/
// Inbox.dc.html) -- `GET .../threads/{id}/messages`, already ordered
// oldest-first by the backend (`sequence.asc()`,
// `product/conversations/messages.py`'s own docstring: deterministic,
// collision-proof ordering, never `created_at`). Bounded pagination
// (limit/offset, same pattern as UI-3's lists) -- never an unbounded
// fetch of a thread's entire history.
//
// Rendered as chat bubbles: `direction === "outbound"` (us) aligns
// right in the accent color, `"inbound"` (the contact) aligns left on a
// plain surface -- an internal note is neither: it was never sent to
// the contact, so it renders with its own distinct "Interne notitie"
// label rather than looking like a real exchanged message (this
// product does have internal notes, unlike the mockup, which shows no
// such case).
import { useEffect } from "react";
import { listMessages, type Message } from "@/lib/api/conversations";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { MessageBody } from "./MessageBody";
import styles from "./MessageList.module.css";

function formatMeta(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function MessageBubble({ message }: { message: Message }) {
  const isOutbound = message.direction === "outbound";
  return (
    <li className={styles.bubbleRow} data-align={isOutbound ? "end" : "start"}>
      <div
        className={styles.bubble}
        data-tone={message.is_internal_note ? "note" : isOutbound ? "outbound" : "inbound"}
      >
        {message.is_internal_note ? <span className={styles.noteLabel}>Interne notitie</span> : null}
        <MessageBody body={message.body} />
      </div>
      <span className={styles.bubbleMeta}>{formatMeta(message.created_at)}</span>
    </li>
  );
}

export function MessageList({
  tenantId,
  threadId,
  reloadKey,
  onRefresh,
}: {
  tenantId: string;
  threadId: string;
  reloadKey?: unknown;
  /** Lets the caller (the thread header) trigger a refresh without this
   * component needing its own visible control -- real, useful capability
   * (asynchronous inbound messages/webhooks aren't pushed live), just
   * relocated rather than dropped to match the mockup's own chrome-free
   * message area. */
  onRefresh?: (refetch: () => void) => void;
}) {
  const query = useApiQuery(
    () => listMessages(tenantId, threadId, { limit: 50 }),
    [tenantId, threadId, reloadKey],
  );

  useEffect(() => {
    onRefresh?.(query.refetch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.refetch]);

  if (query.status === "loading") return <LoadingState label="Berichten laden…" />;
  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="Nog geen berichten"
        description="Verzonden berichten en notities verschijnen hier."
      />
    );
  }

  return (
    <ol className={styles.list} aria-live="polite">
      {query.data.hasMore ? (
        <li className={styles.moreNotice}>Er zijn meer berichten dan hier getoond worden.</li>
      ) : null}
      {query.data.results.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
    </ol>
  );
}
