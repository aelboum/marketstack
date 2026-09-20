"use client";

// Renders `GET /v1/agency/agencies/{agencyTenantId}/clients`. This is
// the only "list" endpoint Phase 3 exposes at all -- there is no client
// detail GET, so `/t/[tenantId]/clients/[clientId]` (the detail page)
// re-fetches this same list and finds its subject inside it, rather than
// fetching it directly (documented gap, see this component's own report
// entry and lib/api/agency.ts's module docstring).
import Link from "next/link";
import { listClients, type ClientSummary } from "@/lib/api/agency";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";

export function ClientsList({
  agencyTenantId,
  reloadKey,
  emptyAction,
  limit,
}: {
  agencyTenantId: string;
  /** Bump this (e.g. after a successful create) to force a refetch. */
  reloadKey?: unknown;
  emptyAction?: React.ReactNode;
  /** Cap how many rows render (the dashboard's compact summary); the
   * full clients page omits this and shows everything the API returned
   * (no pagination -- `list_agency_clients` returns a plain array with
   * no `limit`/`offset`, unlike the CRM list endpoints Phase 4 adds). */
  limit?: number;
}) {
  const query = useApiQuery<ClientSummary[]>(
    () => listClients(agencyTenantId),
    [agencyTenantId, reloadKey],
  );

  if (query.status === "loading") {
    return <LoadingState label="Loading clients…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const clients = query.data;

  if (clients.length === 0) {
    return (
      <EmptyState
        title="No clients yet"
        description="Clients created under this tenant will appear here."
        action={emptyAction}
      />
    );
  }

  const visible = limit ? clients.slice(0, limit) : clients;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {visible.map((client) => (
        <Card key={client.tenant_id}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "var(--space-3)",
              flexWrap: "wrap",
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: "var(--font-weight-medium)" }}>{client.name}</div>
              <div
                style={{
                  fontSize: "var(--font-size-xs)",
                  color: "var(--color-text-faint)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {client.tenant_id}
              </div>
            </div>
            <Link
              href={`/t/${agencyTenantId}/clients/${client.tenant_id}`}
              style={{ fontSize: "var(--font-size-sm)", flexShrink: 0 }}
            >
              View →
            </Link>
          </div>
        </Card>
      ))}
      {limit && clients.length > limit ? (
        <Link
          href={`/t/${agencyTenantId}/clients`}
          style={{ fontSize: "var(--font-size-sm)", alignSelf: "flex-start" }}
        >
          View all {clients.length} clients →
        </Link>
      ) : null}
    </div>
  );
}
