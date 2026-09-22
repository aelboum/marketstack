"use client";

// Conversation detail. Real `GET .../threads/{id}` exists, so this
// fetches the thread directly (unlike UI-2's client detail, which had
// no such route). List and detail are separate routes rather than a
// single split-view page -- on a narrow screen, moving between them is
// just an ordinary link/back navigation, not a JS-driven pane switch
// that needs its own mobile-specific handling.
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { deleteThread, getThread } from "@/lib/api/conversations";
import { getContact } from "@/lib/api/crm";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { MessageList, MessageComposer, AssignThreadForm, useInboxRefresh } from "@/components/conversations";

export default function ThreadDetailPage() {
  const params = useParams<{ tenantId: string; threadId: string }>();
  const { tenantId, threadId } = params;
  const router = useRouter();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [messagesReloadKey, setMessagesReloadKey] = useState(0);
  const { refresh: refreshInbox } = useInboxRefresh();

  const threadQuery = useApiQuery(() => getThread(tenantId, threadId), [tenantId, threadId]);
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteThread(tenantId, threadId));

  const contactId = threadQuery.status === "success" ? threadQuery.data.contact_id : null;
  const contactQuery = useApiQuery(
    () => (contactId ? getContact(tenantId, contactId) : Promise.resolve(null)),
    [tenantId, contactId],
  );

  if (threadQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Gesprek laden…" />
      </Page>
    );
  }
  if (threadQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={threadQuery.error} onRetry={threadQuery.refetch} />
      </Page>
    );
  }

  const thread = threadQuery.data;
  const contactLabel =
    contactQuery.status === "success" && contactQuery.data
      ? `${contactQuery.data.first_name} ${contactQuery.data.last_name}`
      : (thread.contact_id ?? "—");

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/conversations`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Terug naar inbox
        </Link>
      </p>
      <PageHeader
        title={contactLabel}
        description={`Gesprek via ${thread.channel}`}
        actions={
          <Button variant="danger" onClick={() => setConfirmDeleteOpen(true)}>
            Verwijderen
          </Button>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="details-heading">
          <h2 id="details-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Details
          </h2>
          <Card>
            <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginBottom: "var(--space-3)" }}>
              <Badge tone="accent">{thread.channel}</Badge>
              <Badge tone={thread.assigned_to_user_id ? "success" : "neutral"}>
                {thread.assigned_to_user_id ? `Toegewezen aan ${thread.assigned_to_user_id}` : "Niet toegewezen"}
              </Badge>
            </div>
            <AssignThreadForm
              tenantId={tenantId}
              threadId={thread.id}
              currentAssigneeUserId={thread.assigned_to_user_id}
              onAssigned={() => {
                threadQuery.refetch();
                refreshInbox();
              }}
            />
          </Card>
        </section>

        <section aria-labelledby="messages-heading">
          <h2 id="messages-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Berichten
          </h2>
          <MessageList tenantId={tenantId} threadId={thread.id} reloadKey={messagesReloadKey} />
        </section>

        <section aria-labelledby="compose-heading">
          <h2 id="compose-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Nieuw bericht
          </h2>
          <Card>
            <MessageComposer
              tenantId={tenantId}
              threadId={thread.id}
              channel={thread.channel}
              onSent={() => {
                setMessagesReloadKey((key) => key + 1);
                threadQuery.refetch();
                refreshInbox();
              }}
            />
          </Card>
        </section>
      </div>

      {deleteState.status === "error" ? (
        <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Dit gesprek verwijderen?"
        description="Dit kan niet ongedaan worden gemaakt. De volledige berichtgeschiedenis wordt verwijderd."
        confirmLabel="Verwijderen"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          refreshInbox();
          router.push(`/t/${tenantId}/conversations`);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Page>
  );
}
