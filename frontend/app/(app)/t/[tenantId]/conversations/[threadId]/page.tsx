"use client";

// Conversation detail (mockup layout parity: design/Inbox.dc.html).
// Real `GET .../threads/{id}` exists, so this fetches the thread
// directly (unlike UI-2's client detail, which had no such route).
// Messages render as chat bubbles (MessageList), the composer as a
// pinned reply bar (MessageComposer) -- both restyled, neither's
// underlying data/hooks changed. The customer panel (third column) is
// new: `lib/conversations/customerPanel.ts` composes Conversations'
// contact with CRM's most-recent opportunity and Appointments' next
// upcoming appointment for this contact -- real data only, `null`
// fields render as an honest gap, never a placeholder.
//
// The mockup's "Mark done" button is not reproduced: `Thread` has no
// status field (`lib/api/conversations.ts`'s own type), and this pass
// does not invent one -- a control with nothing real behind it would be
// exactly the kind of fabricated feature this product's own conventions
// (docs/ROADMAP.md) rule out. "Delete" (real, pre-existing) is kept,
// relocated into the header instead of dropped to match the mockup's
// two-button header.
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { deleteThread, getThread, type Channel } from "@/lib/api/conversations";
import { getContact } from "@/lib/api/crm";
import { loadCustomerPanel } from "@/lib/conversations/customerPanel";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { Dialog, ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { MessageList, MessageComposer, AssignThreadForm, useInboxRefresh } from "@/components/conversations";
import { formatMoney } from "@/lib/crm/money";
import styles from "./page.module.css";

const CHANNEL_LABELS: Record<Channel, string> = {
  email: "E-mail",
  sms: "SMS",
  whatsapp: "WhatsApp",
  chat: "Chat",
};

function CustomerPanel({ tenantId, contactId }: { tenantId: string; contactId: string }) {
  const query = useApiQuery(() => loadCustomerPanel(tenantId, contactId), [tenantId, contactId]);

  if (query.status === "loading") {
    return (
      <aside className={styles.customerPanel} aria-label="Klant">
        <LoadingState label="Klantgegevens laden…" />
      </aside>
    );
  }
  if (query.status === "error") {
    return (
      <aside className={styles.customerPanel} aria-label="Klant">
        <ApiErrorPanel error={query.error} onRetry={query.refetch} />
      </aside>
    );
  }

  const { contact, latestOpportunity, nextAppointment } = query.data;
  const initials = `${contact.first_name.charAt(0)}${contact.last_name.charAt(0)}`.toUpperCase();
  const since = new Date(contact.created_at).toLocaleDateString("nl-NL", {
    month: "long",
    year: "numeric",
  });

  return (
    <aside className={styles.customerPanel} aria-label="Klant">
      <div className={styles.panelIdentity}>
        <span className={styles.panelAvatar} aria-hidden="true">
          {initials}
        </span>
        <div>
          <div className={styles.panelName}>
            {contact.first_name} {contact.last_name}
          </div>
          <div className={styles.panelSince}>Klant sinds {since}</div>
        </div>
      </div>

      <dl className={styles.panelFields}>
        <dt>E-mail</dt>
        <dd>{contact.email ?? "—"}</dd>
        <dt>Telefoon</dt>
        <dd>{contact.phone ?? "—"}</dd>
      </dl>

      <div className={styles.panelSection}>
        <span className={styles.panelSectionLabel}>Open kans</span>
        {latestOpportunity ? (
          <div className={styles.panelDealCard}>
            <span className={styles.panelDealName}>{latestOpportunity.name}</span>
            <span className={styles.panelDealMeta}>
              {formatMoney(latestOpportunity.amount)} · {latestOpportunity.stageName}
            </span>
          </div>
        ) : (
          <span className={styles.panelDealMeta}>Geen kansen gekoppeld</span>
        )}
      </div>

      <div className={styles.panelSection}>
        <span className={styles.panelSectionLabel}>Volgende afspraak</span>
        <span style={{ fontSize: "var(--font-size-sm)" }}>
          {nextAppointment
            ? new Date(nextAppointment.starts_at).toLocaleString("nl-NL", {
                day: "numeric",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
              })
            : "Niets gepland"}
        </span>
      </div>

      <Link href={`/t/${tenantId}/crm/contacts/${contactId}`} style={{ fontSize: "var(--font-size-sm)" }}>
        Open klant →
      </Link>
    </aside>
  );
}

export default function ThreadDetailPage() {
  const params = useParams<{ tenantId: string; threadId: string }>();
  const { tenantId, threadId } = params;
  const router = useRouter();
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [messagesReloadKey, setMessagesReloadKey] = useState(0);
  const [refetchMessages, setRefetchMessages] = useState<(() => void) | null>(null);
  const { refresh: refreshInbox } = useInboxRefresh();

  const threadQuery = useApiQuery(() => getThread(tenantId, threadId), [tenantId, threadId]);
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteThread(tenantId, threadId));

  // Only for the header's display name -- `CustomerPanel` below fetches
  // the same contact again as part of its own composed query
  // (lib/conversations/customerPanel.ts). Two small GETs for the same
  // record, not one shared fetch: the same accepted, documented tradeoff
  // as the dashboard's own independent-per-widget queries, and simpler
  // than threading the contact down as a prop through a component meant
  // to stay self-contained.
  const contactId = threadQuery.status === "success" ? threadQuery.data.contact_id : null;
  const contactQuery = useApiQuery(
    () => (contactId ? getContact(tenantId, contactId) : Promise.resolve(null)),
    [tenantId, contactId],
  );

  if (threadQuery.status === "loading") {
    return <LoadingState label="Gesprek laden…" />;
  }
  if (threadQuery.status === "error") {
    return <ApiErrorPanel error={threadQuery.error} onRetry={threadQuery.refetch} />;
  }

  const thread = threadQuery.data;
  const contact = contactQuery.status === "success" ? contactQuery.data : null;
  const contactLabel = contact ? `${contact.first_name} ${contact.last_name}` : "Onbekende klant";

  return (
    <div className={styles.wrapper}>
      <header className={styles.header}>
        <Link href={`/t/${tenantId}/conversations`} className={styles.backButton}>
          ← Terug
        </Link>
        <div className={styles.headerInfo}>
          <h1 className={styles.headerName}>{contactLabel}</h1>
          <span className={styles.headerMeta}>
            {CHANNEL_LABELS[thread.channel]}
            {contact?.phone ? ` · ${contact.phone}` : ""}
          </span>
        </div>
        <div className={styles.headerActions}>
          <Button variant="secondary" size="sm" onClick={() => setAssignOpen(true)}>
            Toewijzen
          </Button>
          <Button variant="ghost" size="sm" onClick={() => refetchMessages?.()}>
            Vernieuwen
          </Button>
          <Button variant="danger" size="sm" onClick={() => setConfirmDeleteOpen(true)}>
            Verwijderen
          </Button>
        </div>
      </header>

      <div className={styles.body}>
        <div className={styles.conversationColumn}>
          <MessageList
            tenantId={tenantId}
            threadId={thread.id}
            reloadKey={messagesReloadKey}
            onRefresh={setRefetchMessages}
          />
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
        </div>
        {thread.contact_id ? <CustomerPanel tenantId={tenantId} contactId={thread.contact_id} /> : null}
      </div>

      <Dialog open={assignOpen} onClose={() => setAssignOpen(false)} title="Gesprek toewijzen">
        <AssignThreadForm
          tenantId={tenantId}
          threadId={thread.id}
          currentAssigneeUserId={thread.assigned_to_user_id}
          onAssigned={() => {
            threadQuery.refetch();
            refreshInbox();
            setAssignOpen(false);
          }}
        />
      </Dialog>

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
    </div>
  );
}
