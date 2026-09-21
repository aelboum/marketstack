"use client";

import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { SettingsShell, AccessSettingsPanel } from "@/components/settings";

export default function AccessSettingsPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader title="Settings" description="Workspace, branding, access, and your account." />
      <SettingsShell tenantId={tenantId}>
        <AccessSettingsPanel tenantId={tenantId} />
      </SettingsShell>
    </Page>
  );
}
