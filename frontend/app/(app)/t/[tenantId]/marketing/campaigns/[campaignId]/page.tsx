"use client";

// Campaign detail. Actions are gated to the exact backend lifecycle
// rules confirmed by reading `product/marketing/campaigns.py` and
// `sending.py`: edit/delete only while `status === "draft"`, send only
// while `"draft"`, cancel only while `"sending"`. There is no metrics
// endpoint at all (see `lib/api/marketing.ts` module docstring), so no
// open/click numbers are shown here -- that's a documented gap, not an
// omission.
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  getCampaign,
  deleteCampaign,
  sendCampaign,
  cancelCampaign,
} from "@/lib/api/marketing";
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
import { CampaignForm } from "@/components/marketing/CampaignForm";
import { CampaignRecipientsList } from "@/components/marketing/CampaignRecipientsList";

export default function CampaignDetailPage() {
  const { tenantId, campaignId } = useParams<{ tenantId: string; campaignId: string }>();
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [confirmSendOpen, setConfirmSendOpen] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const [sendResultNotice, setSendResultNotice] = useState<string | null>(null);

  const campaignQuery = useApiQuery(() => getCampaign(tenantId, campaignId), [tenantId, campaignId]);
  const { run: runDelete, state: deleteState } = useAsyncAction(() => deleteCampaign(tenantId, campaignId));
  const { run: runSend, state: sendState } = useAsyncAction(() => sendCampaign(tenantId, campaignId));
  const { run: runCancel, state: cancelState } = useAsyncAction(() => cancelCampaign(tenantId, campaignId));

  if (campaignQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading campaign…" />
      </Page>
    );
  }
  if (campaignQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={campaignQuery.error} onRetry={campaignQuery.refetch} />
      </Page>
    );
  }

  const campaign = campaignQuery.data;
  const canEditOrDelete = campaign.status === "draft";
  const canSend = campaign.status === "draft";
  const canCancel = campaign.status === "sending";

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/marketing/campaigns`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to campaigns
        </Link>
      </p>
      <PageHeader
        title={campaign.name}
        description={`${campaign.channel} campaign`}
        actions={
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            {canSend ? (
              <Button onClick={() => setConfirmSendOpen(true)}>Send</Button>
            ) : null}
            {canCancel ? (
              <Button variant="secondary" onClick={() => setConfirmCancelOpen(true)}>
                Cancel send
              </Button>
            ) : null}
            {canEditOrDelete ? (
              <Button variant="secondary" onClick={() => setEditing((v) => !v)}>
                {editing ? "Close edit" : "Edit"}
              </Button>
            ) : null}
            {canEditOrDelete ? (
              <Button variant="danger" onClick={() => setConfirmDeleteOpen(true)}>
                Delete
              </Button>
            ) : null}
          </div>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="details-heading">
          <h2 id="details-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Details
          </h2>
          <Card>
            <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginBottom: "var(--space-3)" }}>
              <Badge tone="accent">{campaign.channel}</Badge>
              <Badge tone="neutral">{campaign.status}</Badge>
            </div>
            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "var(--space-1) var(--space-3)", fontSize: "var(--font-size-sm)" }}>
              {campaign.subject ? (
                <>
                  <dt style={{ color: "var(--color-text-muted)" }}>Subject</dt>
                  <dd style={{ margin: 0 }}>{campaign.subject}</dd>
                </>
              ) : null}
              <dt style={{ color: "var(--color-text-muted)" }}>Audience</dt>
              <dd style={{ margin: 0 }}>{campaign.segment_query || "Every contact"}</dd>
              <dt style={{ color: "var(--color-text-muted)" }}>Updated</dt>
              <dd style={{ margin: 0 }}>{new Date(campaign.updated_at).toLocaleString()}</dd>
            </dl>
            <div style={{ marginTop: "var(--space-3)", whiteSpace: "pre-wrap", fontSize: "var(--font-size-sm)" }}>{campaign.body}</div>
          </Card>
        </section>

        {editing && canEditOrDelete ? (
          <section aria-labelledby="edit-heading">
            <h2 id="edit-heading" style={{ fontSize: "var(--font-size-md)" }}>
              Edit
            </h2>
            <Card>
              <CampaignForm
                tenantId={tenantId}
                campaign={campaign}
                onSaved={() => {
                  setEditing(false);
                  campaignQuery.refetch();
                }}
              />
            </Card>
          </section>
        ) : null}

        <section aria-labelledby="recipients-heading">
          <h2 id="recipients-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Recipients
          </h2>
          <CampaignRecipientsList tenantId={tenantId} campaignId={campaign.id} />
        </section>
      </div>

      {sendResultNotice ? <InlineNotice tone="success">{sendResultNotice}</InlineNotice> : null}
      {deleteState.status === "error" ? <InlineNotice tone="danger">{deleteState.error.message}</InlineNotice> : null}
      {sendState.status === "error" ? <InlineNotice tone="danger">{sendState.error.message}</InlineNotice> : null}
      {cancelState.status === "error" ? <InlineNotice tone="danger">{cancelState.error.message}</InlineNotice> : null}

      <ConfirmDialog
        open={confirmSendOpen}
        title="Send this campaign?"
        description="This starts a real send to every matching, non-suppressed contact. This cannot be undone."
        confirmLabel="Send"
        pending={sendState.status === "pending"}
        onConfirm={async () => {
          const result = await runSend();
          setConfirmSendOpen(false);
          if (result) {
            setSendResultNotice(
              `Sending to ${result.recipient_count} recipient(s) (${result.suppressed_count} suppressed).`,
            );
            campaignQuery.refetch();
          }
        }}
        onCancel={() => setConfirmSendOpen(false)}
      />
      <ConfirmDialog
        open={confirmCancelOpen}
        title="Cancel this send?"
        description="Stops sending to any recipient not already sent."
        confirmLabel="Cancel send"
        danger
        pending={cancelState.status === "pending"}
        onConfirm={async () => {
          await runCancel();
          setConfirmCancelOpen(false);
          campaignQuery.refetch();
        }}
        onCancel={() => setConfirmCancelOpen(false)}
      />
      <ConfirmDialog
        open={confirmDeleteOpen}
        title="Delete this campaign?"
        description="This cannot be undone."
        confirmLabel="Delete"
        danger
        pending={deleteState.status === "pending"}
        onConfirm={async () => {
          await runDelete();
          router.push(`/t/${tenantId}/marketing/campaigns`);
        }}
        onCancel={() => setConfirmDeleteOpen(false)}
      />
    </Page>
  );
}
