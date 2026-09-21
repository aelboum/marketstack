"use client";

import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { SettingsShell, BrandingSettingsPanel } from "@/components/settings";

export default function BrandingSettingsPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader title="Settings" description="Workspace, branding, access, and your account." />
      <SettingsShell tenantId={tenantId}>
        <BrandingSettingsPanel />
      </SettingsShell>
    </Page>
  );
}
