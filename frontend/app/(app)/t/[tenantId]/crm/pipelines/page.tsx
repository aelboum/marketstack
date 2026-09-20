"use client";

import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { CrmSubNav, PipelinesPanel } from "@/components/crm";

export default function PipelinesPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader title="Pipelines" description="Pipelines and their stages." />
      <CrmSubNav tenantId={tenantId} />
      <PipelinesPanel tenantId={tenantId} />
    </Page>
  );
}
