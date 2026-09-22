"use client";

// Websites hub (UI-12). `lib/nav/config.ts` lists "Websites" as
// available as of this phase -- the backend router has been fully
// mounted (including its purge participant and `agency.role_provisioned`
// event handler) since Phase 11.1's own checkpoint, unlike Reputation's
// deferred-mount history.
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { WebsitesList, CreateWebsiteForm } from "@/components/websites";

export default function WebsitesPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Websites"
        description="Create and manage your tenant's own websites and pages."
        actions={<Button onClick={() => setCreateOpen(true)}>New website</Button>}
      />
      <WebsitesList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            Create a website
          </Button>
        }
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New website">
        <CreateWebsiteForm
          tenantId={tenantId}
          onSaved={() => {
            setCreateOpen(false);
            setReloadKey((key) => key + 1);
          }}
        />
      </Dialog>
    </Page>
  );
}
