"use client";

// The authenticated, tenant-scoped application boundary. Every route
// under `/t/[tenantId]/...` renders through this layout -- it is the one
// place that (a) waits for session initialization, (b) redirects an
// unauthenticated visitor to sign in, and (c) mounts <TenantProvider>
// and <AppShell> around the page. A domain page under this segment never
// re-implements any of this itself (UI-1 requirement: reusable
// authenticated-route boundary, not per-page duplication).
import { useParams, useRouter } from "next/navigation";
import { useSession } from "@/lib/auth/session-context";
import { loginUrl } from "@/lib/auth/api";
import { TenantProvider } from "@/lib/tenant/tenant-context";
import { AppShell } from "@/components/shell/AppShell";
import { LoadingState } from "@/components/ui/states";
import { useEffect } from "react";

export default function TenantAppLayout({ children }: { children: React.ReactNode }) {
  const { status, user, logout } = useSession();
  const params = useParams<{ tenantId: string }>();
  const router = useRouter();
  const tenantId = params.tenantId;

  useEffect(() => {
    if (status === "unauthenticated") {
      window.location.assign(loginUrl());
    }
  }, [status]);

  if (status === "loading") {
    return (
      <div
        style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}
      >
        <LoadingState label="Loading your session…" />
      </div>
    );
  }

  if (status === "unauthenticated" || !user) {
    return (
      <div
        style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}
      >
        <LoadingState label="Redirecting to sign in…" />
      </div>
    );
  }

  return (
    <TenantProvider tenantId={tenantId}>
      <AppShell
        layout="sidebar"
        tenantId={tenantId}
        userId={user.user_id}
        onLogout={async () => {
          await logout();
          router.replace("/");
        }}
      >
        {children}
      </AppShell>
    </TenantProvider>
  );
}
