"use client";

// Wraps `POST /v1/agency/tenants/{tenantId}/invitations` -- works for
// any tenant this actor can invite into (an agency's own tenant, or one
// of its clients; `core.identity.create_invitation()` self-authorizes,
// this panel invents no extra rule). The response's `raw_token` is the
// bearer credential itself and appears exactly once, here -- there is no
// "look it up again" endpoint -- so this panel keeps it on screen with an
// explicit one-time warning rather than silently discarding it.
import { useState } from "react";
import { inviteMember, type InvitationSent } from "@/lib/api/agency";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function InviteMemberPanel({ tenantId }: { tenantId: string }) {
  const [email, setEmail] = useState("");
  const { state, run, reset } = useAsyncAction((invitedEmail: string) =>
    inviteMember(tenantId, invitedEmail),
  );

  const sent: InvitationSent | null = state.status === "success" ? state.data : null;

  if (sent) {
    const acceptLink =
      typeof window !== "undefined"
        ? `${window.location.origin}/accept-invitation?tenant=${tenantId}&token=${encodeURIComponent(sent.raw_token)}`
        : "";
    return (
      <div>
        <InlineNotice tone="success">
          Invitation created for <strong>{email}</strong>.
        </InlineNotice>
        <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
          This link is shown once and won&apos;t be shown again — copy it and send it to the
          invited person yourself (there is no automatic email delivery here).
        </p>
        <Input
          label="Invitation link"
          readOnly
          value={acceptLink}
          onFocus={(event) => event.currentTarget.select()}
        />
        <Button
          variant="secondary"
          size="sm"
          style={{ marginTop: "var(--space-2)" }}
          onClick={() => {
            setEmail("");
            reset();
          }}
        >
          Invite someone else
        </Button>
      </div>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (email.trim()) run(email.trim());
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Email address"
        type="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="teammate@example.com"
      />
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !email.trim()}>
        {state.status === "pending" ? "Sending…" : "Send invitation"}
      </Button>
    </form>
  );
}
