"use client";

// The tenant-less entry point (`/dashboard`, no `[tenantId]`). Its only
// job is to get an authenticated user to a real, tenant-scoped route
// (`/t/[tenantId]/dashboard`) -- it renders no product functionality
// itself. See lib/tenant/last-tenant.ts for why this falls back to a
// manual tenant-id field rather than a real switcher: the backend
// exposes no "list my tenants" endpoint yet (documented gap, UI-1 final
// report), so there is nothing to enumerate.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/auth/session-context";
import { getLastTenantId } from "@/lib/tenant/last-tenant";
import { LoadingState } from "@/components/ui/states";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { loginUrl } from "@/lib/auth/api";

export default function DashboardEntryPage() {
  const { status } = useSession();
  const router = useRouter();
  const [manualTenantId, setManualTenantId] = useState("");
  const [checkedLastTenant, setCheckedLastTenant] = useState(false);

  useEffect(() => {
    if (status !== "authenticated") return;
    const lastTenantId = getLastTenantId();
    if (lastTenantId) {
      router.replace(`/t/${lastTenantId}/dashboard`);
      return;
    }
    setCheckedLastTenant(true);
  }, [status, router]);

  useEffect(() => {
    if (status === "unauthenticated") {
      window.location.assign(loginUrl());
    }
  }, [status]);

  if (status === "loading" || (status === "authenticated" && !checkedLastTenant)) {
    return (
      <main
        style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}
      >
        <LoadingState label="Loading your workspace…" />
      </main>
    );
  }

  if (status === "unauthenticated") {
    return (
      <main
        style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}
      >
        <LoadingState label="Redirecting to sign in…" />
      </main>
    );
  }

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
      <Card style={{ maxWidth: 380, width: "100%" }}>
        <h1 style={{ margin: "0 0 var(--space-2)", fontSize: "var(--font-size-lg)" }}>
          No workspace selected
        </h1>
        <p
          style={{
            margin: "0 0 var(--space-4)",
            color: "var(--color-text-muted)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          We don&apos;t yet have a way to list every workspace (agency/client tenant) you belong
          to -- a tenant switcher arrives in a later UI phase (UI-2). If you have a tenant id,
          enter it below to continue.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (manualTenantId.trim()) {
              router.push(`/t/${manualTenantId.trim()}/dashboard`);
            }
          }}
          style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
        >
          <Input
            label="Tenant ID"
            placeholder="00000000-0000-0000-0000-000000000000"
            value={manualTenantId}
            onChange={(event) => setManualTenantId(event.target.value)}
          />
          <Button type="submit" disabled={!manualTenantId.trim()}>
            Continue
          </Button>
        </form>
      </Card>
    </main>
  );
}
