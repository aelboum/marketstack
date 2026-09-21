"use client";

// Access / administration for the *current* workspace.
//
// This composes the panels UI-2 already built against the real agency
// API rather than reimplementing them: `InviteMemberPanel` and
// `AccessDelegationPanel` both take a `tenantId` and were written for a
// client workspace viewed from an agency. Pointing them at the tenant in
// context is the whole change -- the endpoints, the error handling, and
// the documented "no list endpoint" caveats they already carry are
// identical.
//
// Every route behind these panels is owner-only: the `member` role
// receives no agency-administration grants at all, so a member gets the
// same non-enumerating 404 the panels already render. The UI does not
// pre-check that, because no endpoint reports the caller's own role --
// the backend answers, and the panel shows the answer.
import { InviteMemberPanel, AccessDelegationPanel } from "@/components/agency";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { SettingsSection } from "./SettingsShell";

export function AccessSettingsPanel({ tenantId }: { tenantId: string }) {
  return (
    <>
      <SettingsSection
        title="Teammates"
        description="Invite someone into this workspace."
      >
        <InlineNotice tone="neutral">
          There is no members list: the API exposes no route that lists a workspace&apos;s members,
          roles, or pending invitations. Inviting is the only membership action available here.
        </InlineNotice>
        <InviteMemberPanel tenantId={tenantId} />
      </SettingsSection>

      <SettingsSection
        title="Delegated administration"
        description="Grant or deny a specific permission to a specific user."
      >
        <AccessDelegationPanel tenantId={tenantId} />
      </SettingsSection>
    </>
  );
}
