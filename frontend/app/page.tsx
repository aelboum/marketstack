// Public landing page (docs/ROADMAP.md Phase 1.6, restyled in UI-1 using
// the design-token foundation -- behavior is unchanged from Phase 1.6:
// the login link is a real browser navigation to the backend's own
// /auth/login, which mounts the full OIDC redirect/callback/session-
// cookie flow server-side (saas-os's api.auth.routes) -- this frontend
// still implements no auth logic of its own. A real <a href> (not a
// button+onClick) so it stays a server component and is
// keyboard/middle-click/screen-reader correct.
import { loginUrl } from "@/lib/auth/api";
import { Card } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/Button";

export default function HomePage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "var(--space-4)",
      }}
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
