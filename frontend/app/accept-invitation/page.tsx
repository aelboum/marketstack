"use client";

// Not tenant-scoped (no `[tenantId]` segment) and deliberately outside
// `(app)/t/[tenantId]`'s shell: accepting an invitation is how a user
// gets their *first* membership in a tenant, so there may be no tenant
// context to render a shell around yet. Still requires a real session
// (the accept route itself needs one) -- mirrors the small inline
// auth-guard `app/dashboard/page.tsx` already uses, not a second pattern.
import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useSession } from "@/lib/auth/session-context";
import { loginUrl } from "@/lib/auth/api";
import { LoadingState } from "@/components/ui/states";
import { Card } from "@/components/ui/Card";
import { AcceptInvitationForm } from "@/components/agency/AcceptInvitationForm";

export default function AcceptInvitationPage() {
  return (
    <Suspense
      fallback={
        <main
          className="full-page-center"
        >
          <LoadingState label="Loading…" />
        </main>
      }
    >
      <AcceptInvitationPageContent />
    </Suspense>
  );
}

function AcceptInvitationPageContent() {
  const { status } = useSession();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (status === "unauthenticated") {
      window.location.assign(loginUrl());
    }
  }, [status]);

  if (status === "loading" || status === "unauthenticated") {
    return (
      <main
        className="full-page-center"
      >
        <LoadingState label={status === "loading" ? "Loading…" : "Redirecting to sign in…"} />
      </main>
    );
  }

  return (
    <main
      className="full-page-center"
    >
      <Card style={{ maxWidth: 420, width: "100%" }}>
        <h1 style={{ margin: "0 0 var(--space-2)", fontSize: "var(--font-size-lg)" }}>
          Accept invitation
        </h1>
        <p
          style={{
            margin: "0 0 var(--space-4)",
            color: "var(--color-text-muted)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          Enter the tenant ID and invitation token from your invite link.
        </p>
        <AcceptInvitationForm
          initialTenantId={searchParams.get("tenant") ?? ""}
          initialToken={searchParams.get("token") ?? ""}
        />
      </Card>
    </main>
  );
}
