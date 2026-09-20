"use client";

// Delegated administration and explicit deny (Phase 3.3) --
// `POST/DELETE /v1/agency/tenants/{tenantId}/delegations[/…]` and
// `.../denies[/…]`. Create-and-revoke-by-id only: neither has a list
// endpoint, so there is no "current delegations on this tenant" table to
// show (documented gap -- see this file's own note under each form and
// UI-2's final report). A created grant's id is shown once with an
// explicit "save this to revoke it later" note, the same treatment
// InviteMemberPanel gives a raw invitation token.
import { useState } from "react";
import type { RoleScope } from "@/lib/api/agency";
import { createDelegation, createDeny, revokeDelegation, revokeDeny } from "@/lib/api/agency";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { ResourceActionFields } from "./ResourceActionFields";

function ScopeModeSelect({
  value,
  onChange,
}: {
  value: RoleScope;
  onChange: (value: RoleScope) => void;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
      <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
        Scope
      </span>
      <select value={value} onChange={(event) => onChange(event.target.value as RoleScope)}>
        <option value="self">This tenant only</option>
        <option value="subtree">This tenant and its clients</option>
      </select>
    </label>
  );
}

function CreateDelegationForm({ tenantId }: { tenantId: string }) {
  const [delegateUserId, setDelegateUserId] = useState("");
  const [resource, setResource] = useState("");
  const [action, setAction] = useState("");
  const [scopeMode, setScopeMode] = useState<RoleScope>("self");
  const [expiresAt, setExpiresAt] = useState("");
  const [allowRedelegate, setAllowRedelegate] = useState(false);
  const { state, run } = useAsyncAction(() =>
    createDelegation(tenantId, {
      delegateUserId,
      resource,
      action,
      scopeMode,
      expiresAt: expiresAt ? new Date(expiresAt).toISOString() : null,
      allowRedelegate,
    }),
  );

  if (state.status === "success") {
    return (
      <InlineNotice tone="success">
        Delegation created — id <code>{state.data.delegation_id}</code>. There is no listing for
        current delegations; save this id if you may need to revoke it later.
      </InlineNotice>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (delegateUserId.trim() && resource.trim() && action.trim()) run();
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Delegate user ID (UUID)"
        required
        value={delegateUserId}
        onChange={(event) => setDelegateUserId(event.target.value)}
        placeholder="00000000-0000-0000-0000-000000000000"
      />
      <ResourceActionFields
        resource={resource}
        action={action}
        onResourceChange={setResource}
        onActionChange={setAction}
      />
      <ScopeModeSelect value={scopeMode} onChange={setScopeMode} />
      <Input
        label="Expires at (optional)"
        type="datetime-local"
        value={expiresAt}
        onChange={(event) => setExpiresAt(event.target.value)}
      />
      <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
        <input
          type="checkbox"
          checked={allowRedelegate}
          onChange={(event) => setAllowRedelegate(event.target.checked)}
        />
        Allow the delegate to re-delegate this permission
      </label>
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending"}>
        {state.status === "pending" ? "Creating…" : "Create delegation"}
      </Button>
    </form>
  );
}

function RevokeByIdForm({
  label,
  onRevoke,
  confirmTitle,
}: {
  label: string;
  onRevoke: (id: string) => Promise<unknown>;
  confirmTitle: string;
}) {
  const [id, setId] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { state, run } = useAsyncAction(onRevoke);

  if (state.status === "success") {
    return <InlineNotice tone="success">Revoked.</InlineNotice>;
  }

  return (
    <>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (id.trim()) setConfirmOpen(true);
        }}
        style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}
      >
        <div style={{ flex: 1, minWidth: 220 }}>
          <Input
            label={label}
            required
            value={id}
            onChange={(event) => setId(event.target.value)}
            placeholder="00000000-0000-0000-0000-000000000000"
          />
        </div>
        <Button type="submit" variant="danger" disabled={state.status === "pending" || !id.trim()}>
          Revoke
        </Button>
      </form>
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmOpen}
        title={confirmTitle}
        description="This cannot be undone. The affected access is removed immediately."
        confirmLabel="Revoke"
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          await run(id.trim());
          setConfirmOpen(false);
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}

function CreateDenyForm({ tenantId }: { tenantId: string }) {
  const [principalUserId, setPrincipalUserId] = useState("");
  const [resource, setResource] = useState("");
  const [action, setAction] = useState("");
  const [scopeMode, setScopeMode] = useState<RoleScope>("self");
  const { state, run } = useAsyncAction(() =>
    createDeny(tenantId, { principalUserId, resource, action, scopeMode }),
  );

  if (state.status === "success") {
    return (
      <InlineNotice tone="success">
        Explicit deny created — id <code>{state.data.deny_id}</code>. There is no listing for
        current denies; save this id if you may need to revoke it later.
      </InlineNotice>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (principalUserId.trim() && resource.trim() && action.trim()) run();
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Principal user ID (UUID)"
        required
        value={principalUserId}
        onChange={(event) => setPrincipalUserId(event.target.value)}
        placeholder="00000000-0000-0000-0000-000000000000"
      />
      <ResourceActionFields
        resource={resource}
        action={action}
        onResourceChange={setResource}
        onActionChange={setAction}
      />
      <ScopeModeSelect value={scopeMode} onChange={setScopeMode} />
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" variant="danger" disabled={state.status === "pending"}>
        {state.status === "pending" ? "Creating…" : "Create explicit deny"}
      </Button>
    </form>
  );
}

export function AccessDelegationPanel({ tenantId }: { tenantId: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <InlineNotice tone="neutral">
        There is currently no way to list existing delegations or denies on this tenant — only
        create and revoke-by-id. Keep a record of any id you create.
      </InlineNotice>

      <Card>
        <h3 style={{ marginTop: 0 }}>Grant a delegation</h3>
        <CreateDelegationForm tenantId={tenantId} />
      </Card>

      <Card>
        <h3 style={{ marginTop: 0 }}>Revoke a delegation</h3>
        <RevokeByIdForm
          label="Delegation ID"
          confirmTitle="Revoke this delegation?"
          onRevoke={(id) => revokeDelegation(tenantId, id)}
        />
      </Card>

      <Card>
        <h3 style={{ marginTop: 0 }}>Create an explicit deny</h3>
        <CreateDenyForm tenantId={tenantId} />
      </Card>

      <Card>
        <h3 style={{ marginTop: 0 }}>Revoke an explicit deny</h3>
        <RevokeByIdForm
          label="Deny ID"
          confirmTitle="Revoke this explicit deny?"
          onRevoke={(id) => revokeDeny(tenantId, id)}
        />
      </Card>
    </div>
  );
}
