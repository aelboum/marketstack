"use client";

// Wraps `POST /v1/agency/tenants/{tenantId}/invitations/accept`. The
// accepting user must already be signed in (the route uses
// `get_current_actor`) -- the containing page handles that boundary;
// this component only handles the token/tenant form and the real
// backend outcomes: success, or the single collapsed 400 the backend
// deliberately returns for every kind of invalid token
// (`product/agency/routes.py::accept_invitation_route`'s own docstring
// -- unknown/expired/revoked/already-accepted/wrong-tenant are all the
// identical response, on purpose, and this form shows that message
// verbatim rather than guessing which one it was).
//
// A successful accept now genuinely completes onboarding: the backend
// remediation in `product/agency/onboarding.py::accept_client_invitation()`
// (commit `2efe21708cca90e257caea7c68d59d4b80ad6a62`) chains the
// newly-accepted member's starting "member" role assignment onto a
// successful accept, using the invitation's own inviter as the granting
// actor -- see that function's own docstring for the full reasoning.
// The response shape this form consumes is unchanged
// (`InvitationAccepted` = `{tenant_id, membership_id}`, from
// `product/agency/routes.py::accept_invitation_route`) -- it carries no
// role/permission field, and this form does not invent one; the success
// message below states only what the backend actually guarantees
// (membership + starting role assigned), never a specific permission
// list the response doesn't report.
import { useState } from "react";
import Link from "next/link";
import { acceptInvitation, type InvitationAccepted } from "@/lib/api/agency";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function AcceptInvitationForm({
  initialTenantId = "",
  initialToken = "",
}: {
  initialTenantId?: string;
  initialToken?: string;
}) {
  const [tenantId, setTenantId] = useState(initialTenantId);
  const [rawToken, setRawToken] = useState(initialToken);
  const { state, run } = useAsyncAction(() => acceptInvitation(tenantId.trim(), rawToken.trim()));

  const accepted: InvitationAccepted | null = state.status === "success" ? state.data : null;

  if (accepted) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        <InlineNotice tone="success">
          You&apos;ve joined this tenant, with your starting access already in place.
        </InlineNotice>
        <Link href={`/t/${accepted.tenant_id}/dashboard`}>
          <Button>Go to the dashboard</Button>
        </Link>
      </div>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (tenantId.trim() && rawToken.trim()) run();
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Tenant ID"
        required
        value={tenantId}
        onChange={(event) => setTenantId(event.target.value)}
        placeholder="00000000-0000-0000-0000-000000000000"
      />
      <Input
        label="Invitation token"
        required
        value={rawToken}
        onChange={(event) => setRawToken(event.target.value)}
      />
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !tenantId.trim() || !rawToken.trim()}>
        {state.status === "pending" ? "Joining…" : "Accept invitation"}
      </Button>
    </form>
  );
}
