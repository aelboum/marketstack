"use client";

// General workspace settings.
//
// What this can honestly show is narrow, and the reason is worth stating
// precisely. No route in this product reads a single tenant's own record:
// `product/agency/routes.py` has no `GET /tenants/{id}`, no PATCH, and no
// PUT. A tenant's `name` is accepted once, at creation
// (`POST /v1/agency/agencies` or `.../clients`), and is never readable or
// changeable afterwards through the API. The platform does ship a
// `GET /v1/tenants/{id}/status` route that would return `{id, name,
// status}`, but this product does not mount it, so it is unreachable.
//
// So: no name field, and no rename control. The identifier shown below
// is the tenant id already in the URL -- the same value every API call
// on this page is scoped to -- not a lookup.
//
// The one real read available for the current tenant is its client list
// (`GET /v1/agency/agencies/{tenant_id}/clients`), which answers "is this
// workspace an agency, and what does it manage". That call is also the
// page's authorization probe: it is owner-only, and a member (or a
// workspace that is not an agency) gets the same non-enumerating 404,
// which is rendered as the shared permission-denied state rather than
// interpreted.
import Link from "next/link";
import { listClients } from "@/lib/api/agency";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { SettingsSection } from "./SettingsShell";

export function GeneralSettingsPanel({ tenantId }: { tenantId: string }) {
  const clientsQuery = useApiQuery(() => listClients(tenantId), [tenantId]);

  return (
    <>
      <SettingsSection
        title="Workspace"
        description="How this workspace is identified by the API."
      >
        <Card>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              gap: "var(--space-1) var(--space-3)",
              margin: 0,
              fontSize: "var(--font-size-sm)",
            }}
          >
            <dt style={{ color: "var(--color-text-muted)" }}>Workspace ID</dt>
            <dd style={{ margin: 0, wordBreak: "break-all" }}>{tenantId}</dd>
          </dl>

          <p
            style={{
              margin: "var(--space-3) 0 0",
              fontSize: "var(--font-size-xs)",
              color: "var(--color-text-muted)",
            }}
          >
            The workspace name is set when the workspace is created and cannot be read back or
            changed here — the API exposes no route that reads or updates a workspace record.
          </p>
        </Card>
      </SettingsSection>

      <SettingsSection
        title="Client workspaces"
        description="Workspaces this one manages, if it is an agency."
        actions={
          <Link href={`/t/${tenantId}/clients`}>
            <Button variant="secondary" size="sm">
              Open clients
            </Button>
          </Link>
        }
      >
        {clientsQuery.status === "loading" ? (
          <LoadingState label="Loading client workspaces…" />
        ) : clientsQuery.status === "error" ? (
          // Covers all three of: not an agency, no permission (this is an
          // owner-only route), and genuinely absent -- the backend
          // deliberately returns the same 404 for each, and the UI does
          // not pretend to tell them apart.
          <ApiErrorPanel error={clientsQuery.error} onRetry={clientsQuery.refetch} />
        ) : clientsQuery.data.length === 0 ? (
          <EmptyState
            title="No client workspaces"
            description="This workspace does not manage any others."
          />
        ) : (
          <Card>
            <p style={{ marginTop: 0, fontSize: "var(--font-size-sm)" }}>
              Managing {clientsQuery.data.length}{" "}
              {clientsQuery.data.length === 1 ? "client workspace" : "client workspaces"}.
            </p>
            <ul
              style={{
                margin: 0,
                paddingLeft: "var(--space-4)",
                fontSize: "var(--font-size-sm)",
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-1)",
              }}
            >
              {/* The backend returns descendants from an unordered set, so
                  the order is arbitrary -- sorted here for a stable view. */}
              {[...clientsQuery.data]
                .sort((a, b) => a.name.localeCompare(b.name))
                .map((client) => (
                  <li key={client.tenant_id}>
                    <Link href={`/t/${tenantId}/clients/${client.tenant_id}`}>{client.name}</Link>
                  </li>
                ))}
            </ul>
          </Card>
        )}
      </SettingsSection>
    </>
  );
}
