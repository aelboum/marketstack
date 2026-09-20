"use client";

import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { CrmSubNav, CompaniesList, CompanyForm } from "@/components/crm";

export default function CompaniesPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Companies"
        actions={<Button onClick={() => setCreateOpen(true)}>New company</Button>}
      />
      <CrmSubNav tenantId={tenantId} />
      <CompaniesList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={<Button size="sm" onClick={() => setCreateOpen(true)}>Create a company</Button>}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New company">
        <CompanyForm
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
