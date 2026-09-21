"use client";

import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { SettingsShell, ProfileSettingsPanel } from "@/components/settings";

export default function ProfileSettingsPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader title="Settings" description="Workspace, branding, access, and your account." />
      <SettingsShell tenantId={tenantId}>
        <ProfileSettingsPanel />
      </SettingsShell>
    </Page>
  );
}
