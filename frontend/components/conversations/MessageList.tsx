"use client";

// Message history for one thread -- `GET .../threads/{id}/messages`,
// already ordered oldest-first by the backend (`sequence.asc()`,
// `product/conversations/messages.py`'s own docstring: deterministic,
// collision-proof ordering, never `created_at`). Bounded pagination
// (limit/offset, same pattern as UI-3's lists) -- never an unbounded
// fetch of a thread's entire history.
import { listMessages, type Message } from "@/lib/api/conversations";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { MessageBody } from "./MessageBody";

function MessageRow({ message }: { message: Message }) {
  return (
    <Card
      style={{
        borderLeft: message.is_internal_note
          ? "3px solid var(--color-warning)"
          : message.direction === "outbound"
            ? "3px solid var(--color-accent)"
            : "3px solid var(--color-border-strong)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "var(--space-2)",
          gap: "var(--space-2)",
        }}
      >
        <div style={{ display: "flex", gap: "var(--space-1)" }}>
          {message.is_internal_note ? <Badge tone="warning">Internal note</Badge> : null}
          <Badge tone={message.direction === "outbound" ? "accent" : "neutral"}>
            {message.direction === "outbound" ? "Outbound" : "Inbound"}
          </Badge>
        </div>
        <time
          dateTime={message.created_at}
          style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}
        >
          {new Date(message.created_at).toLocaleString()}
        </time>
      </div>
      <MessageBody body={message.body} />
    </Card>
  );
}

export function MessageList({
  tenantId,
  threadId,
  reloadKey,
}: {
  tenantId: string;
  threadId: string;
  reloadKey?: unknown;
}) {
  const query = useApiQuery(
    () => listMessages(tenantId, threadId, { limit: 50 }),
    [tenantId, threadId, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading messages…" />;
  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button variant="secondary" size="sm" onClick={query.refetch}>
          Refresh
        </Button>
      </div>
      {query.data.results.length === 0 ? (
        <EmptyState title="No messages yet" description="Sent messages and notes will appear here." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          {query.data.results.map((message) => (
            <MessageRow key={message.id} message={message} />
          ))}
          {query.data.hasMore ? (
            <p style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)", margin: 0 }}>
              More messages exist than are shown here.
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
