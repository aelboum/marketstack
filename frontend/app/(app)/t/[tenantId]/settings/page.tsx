"use client";

// Settings index — General.
//
// Each settings route renders `PageHeader` + `SettingsShell` and drops a
// panel into it. The page owns no navigation, no layout arrangement, and
// no visual decisions: swapping `SettingsShell`'s `variant` from
// "sidebar" to "tabs" changes every settings route at once, without
// touching any of them.
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { SettingsShell, GeneralSettingsPanel } from "@/components/settings";

export default function SettingsPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader title="Settings" description="Workspace, branding, access, and your account." />
      <SettingsShell tenantId={tenantId}>
        <GeneralSettingsPanel tenantId={tenantId} />
      </SettingsShell>
    </Page>
  );
}
