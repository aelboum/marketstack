"use client";

// Public landing page (docs/ROADMAP.md Phase 1.6, restyled in UI-1 using
// the design-token foundation). The login link is a real browser
// navigation to the backend's own /auth/login, which mounts the full
// OIDC redirect/callback/session-cookie flow server-side (saas-os's
// api.auth.routes) -- this frontend still implements no auth logic of
// its own.
//
// Local single-origin routing phase: now that `/` is served by the
// frontend (the edge routes everything but /auth, /v1, /healthz, /readyz to it --
// see docker-compose.yml), `AUTH_POST_LOGIN_PATH=/` lands an
// authenticated browser back here instead of the backend's own 404.
// This page must therefore hand an authenticated session off to the
// application rather than showing the public landing page underneath
// it. It reuses the existing tenant-resolution entry point
// (`app/dashboard/page.tsx`) rather than re-implementing
// last-tenant/manual-tenant-id/create-agency logic here -- "use client"
// only because that handoff needs `useSession()`.
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/auth/session-context";
import { loginUrl } from "@/lib/auth/api";
import { Card } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";
import { LoadingState } from "@/components/ui/states";

export default function HomePage() {
  const { status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [status, router]);

  // "authenticated" still renders the loading state (not the landing
  // page below) for the one tick before the redirect above commits --
  // otherwise the public landing page would flash for an already
  // signed-in user.
  if (status === "loading" || status === "authenticated") {
    return (
      <main className="full-page-center">
        <LoadingState label="Loading…" />
      </main>
    );
  }

  return (
    <main
      className="full-page-center"
    >
      <Card style={{ maxWidth: 360, width: "100%", textAlign: "center" }}>
        <h1 style={{ margin: "0 0 var(--space-2)", fontSize: "var(--font-size-lg)" }}>Product</h1>
        <p
          style={{
            margin: "0 0 var(--space-5)",
            color: "var(--color-text-muted)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          Sign in to continue to your workspace.
        </p>
        <LinkButton href={loginUrl()}>Log in</LinkButton>
      </Card>
    </main>
  );
}
