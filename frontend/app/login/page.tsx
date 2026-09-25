"use client";

// Product-owned sign-in entry point (docs/ADR/0016-branded-login-ux-vs-
// provider-agnosticism.md: keep the existing hosted OIDC redirect as the
// authentication mechanism -- this page changes only what the user sees
// *before* that redirect, never how authentication itself works). It
// implements no auth logic of its own -- same as `app/page.tsx` -- and
// contains no password field: "Sign in" is a real browser navigation to
// the backend's own /auth/login, which mounts the full OIDC
// redirect/callback/session-cookie flow server-side (saas-os's
// api.auth.routes). ZITADEL's hostname never appears in this page's copy.
//
// "Product" is the same ADR-0001 neutral placeholder `app/page.tsx` and
// `app/layout.tsx`'s metadata already use -- there is no tenant-branding
// API yet for the frontend to read (frontend/lib/settings/config.ts's own
// "branding" area is `status: "unavailable"` for exactly this reason),
// and `/login` is reached before any tenant is known regardless, so a
// per-tenant brand could never apply here even once that API exists.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/auth/session-context";
import { loginUrl } from "@/lib/auth/api";
import { Card } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";
import { LoadingState } from "@/components/ui/states";

export default function LoginPage() {
  const { status } = useSession();
  const router = useRouter();
  const [redirecting, setRedirecting] = useState(false);

  // Landing here already signed in (e.g. a stale bookmark, or the
  // "/" -> "/login" handoff below racing a session that resolved in
  // another tab) goes straight to the app, never a stale sign-in card.
  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [status, router]);

  if (status === "loading" || status === "authenticated" || redirecting) {
    return (
      <main className="full-page-center">
        <LoadingState label={redirecting ? "Redirecting to sign in…" : "Loading…"} />
      </main>
    );
  }

  return (
    <main className="full-page-center">
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
        {/* A real <a href> (not a button+onClick that preventDefaults) --
            keyboard/middle-click/screen-reader correct, exactly like
            app/page.tsx's own login link. The onClick only adds visible
            feedback for the redirect that is about to happen; it never
            blocks or replaces the anchor's own navigation. */}
        <LinkButton href={loginUrl()} onClick={() => setRedirecting(true)}>
          Sign in
        </LinkButton>
      </Card>
    </main>
  );
}
