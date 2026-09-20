"use client";

// The tenant-less entry point (`/dashboard`, no `[tenantId]`). Its only
// job is to get an authenticated user to a real, tenant-scoped route
// (`/t/[tenantId]/dashboard`) -- it renders no product functionality
// itself. See lib/tenant/last-tenant.ts for why this falls back to a
// manual tenant-id field rather than a real switcher: the backend still
// exposes no "list my tenants" endpoint as of UI-2 either (confirmed
// again while building UI-2 -- see this phase's final report), so there
// is nothing to enumerate. UI-2 does add one genuinely new way out of
// this state though: `POST /v1/agency/agencies` is real, ungated
// self-service signup (`product/agency/provisioning.py::provision_agency()`'s
// own docstring) -- a user with no tenant at all can create one here.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/auth/session-context";
import { getLastTenantId } from "@/lib/tenant/last-tenant";
import { createAgency } from "@/lib/api/agency";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState } from "@/components/ui/states";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { loginUrl } from "@/lib/auth/api";

export default function DashboardEntryPage() {
  const { status } = useSession();
  const router = useRouter();
  const [manualTenantId, setManualTenantId] = useState("");
  const [checkedLastTenant, setCheckedLastTenant] = useState(false);
  const [newAgencyName, setNewAgencyName] = useState("");
  const { state: createAgencyState, run: runCreateAgency } = useAsyncAction((name: string) =>
    createAgency(name),
  );

  useEffect(() => {
    if (createAgencyState.status === "success") {
      router.push(`/t/${createAgencyState.data.tenant_id}/dashboard`);
    }
  }, [createAgencyState, router]);

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
          There&apos;s no way yet to list every workspace (agency/client tenant) you belong to.
          If you have a tenant id, enter it below to continue.
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

        <hr style={{ margin: "var(--space-5) 0", border: "none", borderTop: "1px solid var(--color-border)" }} />

        <h2 style={{ margin: "0 0 var(--space-2)", fontSize: "var(--font-size-md)" }}>
          Or start a new agency
        </h2>
        <p
          style={{
            margin: "0 0 var(--space-3)",
            color: "var(--color-text-muted)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          Creates a brand-new agency tenant with you as its owner.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (newAgencyName.trim()) runCreateAgency(newAgencyName.trim());
          }}
          style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
        >
          <Input
            label="Agency name"
            placeholder="Acme Marketing"
            value={newAgencyName}
            onChange={(event) => setNewAgencyName(event.target.value)}
          />
          {createAgencyState.status === "error" ? (
            <InlineNotice tone="danger">{createAgencyState.error.message}</InlineNotice>
          ) : null}
          <Button
            type="submit"
            variant="secondary"
            disabled={createAgencyState.status === "pending" || !newAgencyName.trim()}
          >
            {createAgencyState.status === "pending" ? "Creating…" : "Create agency"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
