"use client";

// Support access workflow (Phase 3.4) -- the roadmap's own words: "the
// kind of 'temporary convenience backdoor' saas-os docs/SECURITY.md
// warns against building outside the sanctioned mechanism." Every
// action here is destructive/sensitive enough to require explicit
// confirmation (docs/ROADMAP.md UI Track UI-2 scope, item 9). Like
// delegations/denies, there is no list endpoint -- approve/deny/revoke
// all require already knowing a `request_id`, which this panel cannot
// discover on its own (documented gap).
import { useState } from "react";
import type { RoleScope } from "@/lib/api/agency";
import {
  approveSupportAccess,
  denySupportAccess,
  requestSupportAccess,
  revokeSupportAccess,
} from "@/lib/api/agency";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { FormRow } from "@/components/ui/FormRow";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";

function RequestSupportAccessForm({ tenantId }: { tenantId: string }) {
  const [reason, setReason] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [scopeMode, setScopeMode] = useState<RoleScope>("self");
  const { state, run } = useAsyncAction(() =>
    requestSupportAccess(tenantId, {
      reason,
      requestedExpiresAt: new Date(expiresAt).toISOString(),
      scopeMode,
    }),
  );

  if (state.status === "success") {
    return (
      <InlineNotice tone="success">
        Support-access request created — id <code>{state.data.request_id}</code>. Share this id
        with whoever needs to approve it; there is no request inbox to find it in otherwise.
      </InlineNotice>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (reason.trim() && expiresAt) run();
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Reason"
        required
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Troubleshooting a support ticket…"
      />
      <Input
        label="Access needed until"
        type="datetime-local"
        required
        value={expiresAt}
        onChange={(event) => setExpiresAt(event.target.value)}
      />
      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Scope
        </span>
        <select value={scopeMode} onChange={(event) => setScopeMode(event.target.value as RoleScope)}>
          <option value="self">This tenant only</option>
          <option value="subtree">This tenant and its clients</option>
        </select>
      </label>
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending"}>
        {state.status === "pending" ? "Requesting…" : "Request support access"}
      </Button>
    </form>
  );
}

function DecideByIdForm({
  tenantId,
  label,
  actionLabel,
  confirmTitle,
  confirmDescription,
  decide,
}: {
  tenantId: string;
  label: string;
  actionLabel: string;
  confirmTitle: string;
  confirmDescription: string;
  decide: (tenantId: string, requestId: string) => Promise<{ request_id: string }>;
}) {
  const [requestId, setRequestId] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { state, run } = useAsyncAction((id: string) => decide(tenantId, id));

  if (state.status === "success") {
    return <InlineNotice tone="success">Done.</InlineNotice>;
  }

  return (
    <>
      <FormRow
        onSubmit={(event) => {
          event.preventDefault();
          if (requestId.trim()) setConfirmOpen(true);
        }}
      >
        <div style={{ flex: 1, minWidth: 220 }}>
          <Input
            label={label}
            required
            value={requestId}
            onChange={(event) => setRequestId(event.target.value)}
            placeholder="00000000-0000-0000-0000-000000000000"
          />
        </div>
        <Button type="submit" disabled={state.status === "pending" || !requestId.trim()}>
          {actionLabel}
        </Button>
      </FormRow>
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmOpen}
        title={confirmTitle}
        description={confirmDescription}
        confirmLabel={actionLabel}
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          await run(requestId.trim());
          setConfirmOpen(false);
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}

export function SupportAccessPanel({ tenantId }: { tenantId: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <InlineNotice tone="neutral">
        There is no inbox of pending support-access requests here — a request id must be shared
        out of band before it can be approved, denied, or revoked.
      </InlineNotice>

      <Card>
        <h3 style={{ marginTop: 0 }}>Request support access</h3>
        <RequestSupportAccessForm tenantId={tenantId} />
      </Card>

      <Card>
        <h3 style={{ marginTop: 0 }}>Approve a request</h3>
        <DecideByIdForm
          tenantId={tenantId}
          label="Request ID"
          actionLabel="Approve"
          confirmTitle="Approve this support-access request?"
          confirmDescription="This grants time-boxed access immediately. Only approve a request you recognize."
          decide={approveSupportAccess}
        />
      </Card>

      <Card>
        <h3 style={{ marginTop: 0 }}>Deny a request</h3>
        <DecideByIdForm
          tenantId={tenantId}
          label="Request ID"
          actionLabel="Deny"
          confirmTitle="Deny this support-access request?"
          confirmDescription="The requester will not receive the access they asked for."
          decide={denySupportAccess}
        />
      </Card>

      <Card>
        <h3 style={{ marginTop: 0 }}>Revoke active support access</h3>
        <DecideByIdForm
          tenantId={tenantId}
          label="Request ID"
          actionLabel="Revoke"
          confirmTitle="Revoke this support access?"
          confirmDescription="Access already granted under this request ends immediately."
          decide={revokeSupportAccess}
        />
      </Card>
    </div>
  );
}
