"use client";

// Client detail. There is no `GET .../clients/{clientId}` route
// (verified by reading product/agency/routes.py) -- so this page
// re-fetches the parent's client list (the one real list endpoint that
// exists) and finds its subject inside it, rather than fetching it
// directly. A `clientId` that isn't in that list -- because it doesn't
// exist, or because this actor can't see it, or the actor can't even
// read the parent's client list at all -- all render the identical
// PermissionDeniedState: this page has no way to distinguish those
// cases and must not pretend to (docs/ROADMAP.md UI Track's
// non-enumeration requirement, carried over from UI-1).
import { useParams } from "next/navigation";
import { listClients, type ClientSummary } from "@/lib/api/agency";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { LoadingState, PermissionDeniedState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { InviteMemberPanel, AccessDelegationPanel, SupportAccessPanel } from "@/components/agency";

export default function ClientDetailPage() {
  const params = useParams<{ tenantId: string; clientId: string }>();
  const { tenantId: agencyTenantId, clientId } = params;

  const query = useApiQuery<ClientSummary[]>(
    () => listClients(agencyTenantId),
    [agencyTenantId],
  );

  if (query.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading client…" />
      </Page>
    );
  }

  if (query.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={query.error} onRetry={query.refetch} />
      </Page>
    );
  }

  const client = query.data.find((candidate) => candidate.tenant_id === clientId);

  if (!client) {
    return (
      <Page>
        <PermissionDeniedState />
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader title={client.name} description={client.tenant_id} />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="invite-heading">
          <h2 id="invite-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Invite a member
          </h2>
          <Card>
            <InviteMemberPanel tenantId={client.tenant_id} />
          </Card>
        </section>

        <section aria-labelledby="access-heading">
          <h2 id="access-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Access &amp; delegation
          </h2>
          <AccessDelegationPanel tenantId={client.tenant_id} />
        </section>

        <section aria-labelledby="support-heading">
          <h2 id="support-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Support access
          </h2>
          <SupportAccessPanel tenantId={client.tenant_id} />
        </section>
      </div>
    </Page>
  );
}
