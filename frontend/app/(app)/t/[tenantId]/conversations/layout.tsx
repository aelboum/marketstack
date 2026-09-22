"use client";

// Wraps every `/t/[tenantId]/conversations/*` route in the Unified
// Inbox's split-view shell (docs/ROADMAP.md Phase 30). The bare list
// page and the per-thread detail page below are unaffected by which
// pane arrangement is active -- exactly the same "a page never owns the
// shell's layout decision" rule `components/settings/SettingsShell.tsx`
// already established for Settings.
import { useParams } from "next/navigation";
import { InboxShell } from "@/components/conversations";

export default function ConversationsLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ tenantId: string }>();
  return <InboxShell tenantId={params.tenantId}>{children}</InboxShell>;
}
