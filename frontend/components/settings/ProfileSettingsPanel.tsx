"use client";

// Profile / account settings.
//
// Everything shown here comes from the one real profile contract this
// product has: the platform's `GET /auth/me`, which returns a single
// field -- `user_id`. That route's own docstring is explicit that it
// deliberately returns nothing else (which tenants a user may act in is
// answered per-tenant by membership-checked routes, not here).
//
// So there is no display name, email, avatar, locale, timezone, or
// notification preference to edit: no endpoint exposes or accepts any of
// them, and inventing a form that writes them nowhere would be fake
// persistence. The editable-profile gap is stated on the page instead,
// and recorded in UI-7's report.
//
// The two real actions are session actions, and both already exist in
// UI-1's session context: re-check the session, and sign out.
import { useState } from "react";
import { useSession } from "@/lib/auth/session-context";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { SettingsSection } from "./SettingsShell";

export function ProfileSettingsPanel() {
  const { status, user, refresh, logout } = useSession();
  const [confirmSignOutOpen, setConfirmSignOutOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  return (
    <>
      <SettingsSection
        title="Account"
        description="The signed-in identity this session is acting as."
      >
        <Card>
          {status === "loading" ? (
            <LoadingState label="Checking your session…" />
          ) : status === "unauthenticated" || !user ? (
            // Not an error panel: an unauthenticated session on the
            // profile page is an expected state, and the app-wide
            // session handling already drives re-authentication.
            <InlineNotice tone="warning">
              You are not signed in. Sign in again to see your account details.
            </InlineNotice>
          ) : (
            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "var(--space-1) var(--space-3)",
                margin: 0,
                fontSize: "var(--font-size-sm)",
              }}
            >
              <dt style={{ color: "var(--color-text-muted)" }}>User ID</dt>
              <dd style={{ margin: 0, wordBreak: "break-all" }}>{user.user_id}</dd>
              <dt style={{ color: "var(--color-text-muted)" }}>Session</dt>
              <dd style={{ margin: 0 }}>
                <Badge tone="success">Signed in</Badge>
              </dd>
            </dl>
          )}

          <p
            style={{
              margin: "var(--space-3) 0 0",
              fontSize: "var(--font-size-xs)",
              color: "var(--color-text-muted)",
            }}
          >
            Name, email, and notification preferences are not editable here: the platform exposes
            no profile endpoint beyond the signed-in user ID. Identity details are managed by the
            identity provider used to sign in.
          </p>
        </Card>
      </SettingsSection>

      <SettingsSection title="Session" description="Re-check or end this browser session.">
        <Card>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <Button variant="secondary" onClick={refresh} disabled={status === "loading"}>
              {status === "loading" ? "Checking…" : "Re-check session"}
            </Button>
            <Button
              variant="danger"
              onClick={() => setConfirmSignOutOpen(true)}
              disabled={status !== "authenticated"}
            >
              Sign out
            </Button>
          </div>
        </Card>
      </SettingsSection>

      <ConfirmDialog
        open={confirmSignOutOpen}
        title="Sign out?"
        description="This ends your session in this browser. You will need to sign in again to continue."
        confirmLabel="Sign out"
        cancelLabel="Stay signed in"
        danger
        pending={signingOut}
        onConfirm={async () => {
          setSigningOut(true);
          try {
            await logout();
          } finally {
            setSigningOut(false);
            setConfirmSignOutOpen(false);
          }
        }}
        onCancel={() => setConfirmSignOutOpen(false)}
      />
    </>
  );
}
