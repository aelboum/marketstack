"use client";

import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { CrmSubNav, OpportunitiesList, OpportunityForm } from "@/components/crm";

export default function OpportunitiesPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Opportunities"
        actions={<Button onClick={() => setCreateOpen(true)}>New opportunity</Button>}
      />
      <CrmSubNav tenantId={tenantId} />
      <OpportunitiesList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={<Button size="sm" onClick={() => setCreateOpen(true)}>Create an opportunity</Button>}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New opportunity">
        <OpportunityForm
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
