"use client";

import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { SuppressionsList, CreateSuppressionForm, MarketingSubNav } from "@/components/marketing";

export default function SuppressionsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader title="Suppressions" actions={<Button onClick={() => setCreateOpen(true)}>Add suppression</Button>} />
      <MarketingSubNav tenantId={tenantId} />
      <SuppressionsList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={<Button size="sm" onClick={() => setCreateOpen(true)}>Add a suppression</Button>}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="Add suppression">
        <CreateSuppressionForm
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
