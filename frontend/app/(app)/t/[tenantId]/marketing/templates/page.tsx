"use client";

import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { TemplatesPanel, MarketingSubNav } from "@/components/marketing";

export default function MarketingTemplatesPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader title="Templates" />
      <MarketingSubNav tenantId={tenantId} />
      <TemplatesPanel tenantId={tenantId} />
    </Page>
  );
}
