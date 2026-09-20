"use client";

import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FormsList, CreateFormForm, MarketingSubNav } from "@/components/marketing";

export default function FormsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader title="Forms" actions={<Button onClick={() => setCreateOpen(true)}>New form</Button>} />
      <MarketingSubNav tenantId={tenantId} />
      <FormsList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={<Button size="sm" onClick={() => setCreateOpen(true)}>Create a form</Button>}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New form">
        <CreateFormForm
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
