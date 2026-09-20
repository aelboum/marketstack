"use client";

// Same campaign list as the Marketing hub (marketing/page.tsx), reached
// via MarketingSubNav's "Campaigns" link and from other sections'
// "back" links -- kept as its own route rather than redirecting so the
// sub-nav's active-tab state stays correct.
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { CampaignsList, CampaignForm, MarketingSubNav } from "@/components/marketing";

export default function CampaignsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader title="Campaigns" actions={<Button onClick={() => setCreateOpen(true)}>New campaign</Button>} />
      <MarketingSubNav tenantId={tenantId} />
      <CampaignsList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={<Button size="sm" onClick={() => setCreateOpen(true)}>Create a campaign</Button>}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New campaign">
        <CampaignForm
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
