"use client";

// Support access for the current workspace -- time-boxed access a parent
// agency requests and this workspace's owner approves, denies, or
// revokes.
//
// Reuses UI-2's `SupportAccessPanel` against the tenant in context. That
// panel already documents the real constraint: there is no inbox of
// pending requests, because no list route exists -- approve/deny/revoke
// all need a `request_id` that only the requester's own create response
// produced.
import { SupportAccessPanel } from "@/components/agency";
import { SettingsSection } from "./SettingsShell";

export function SupportAccessSettingsPanel({ tenantId }: { tenantId: string }) {
  return (
    <SettingsSection
      title="Support access"
      description="Request, approve, deny, or revoke time-boxed access for a parent agency."
    >
      <SupportAccessPanel tenantId={tenantId} />
    </SettingsSection>
  );
}
