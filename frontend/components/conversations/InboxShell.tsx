"use client";

// The Unified Inbox's replaceable split-view shell (docs/ROADMAP.md
// Phase 30) -- mirrors `components/settings/SettingsShell.tsx`'s own
// "shell owns the layout, a page owns none of it" discipline. Renders
// `InboxList` in a persistent left pane and `children` (the bare inbox
// page's own empty-state, or a selected thread's detail page) in the
// right pane -- desktop shows both at once; a narrow viewport shows
// exactly one, chosen by the current route via `usePathname()`, never a
// separate mobile-only navigation state machine.
//
// The `/conversations/templates` sub-route is message-template
// management, not a thread detail -- deliberately rendered as a plain
// passthrough (no inbox list wrapped around it) rather than forced into
// a shell built for a different screen.
import { usePathname } from "next/navigation";
import { InboxList } from "./InboxList";
import { InboxRefreshProvider, useInboxRefresh } from "./InboxRefreshContext";
import styles from "./InboxShell.module.css";

function InboxShellContent({
  tenantId,
  children,
}: {
  tenantId: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { reloadKey } = useInboxRefresh();
  const basePath = `/t/${tenantId}/conversations`;
  const detailOpen = pathname !== basePath;

  return (
    <div className={styles.shell} data-detail-open={detailOpen} data-testid="inbox-shell">
      <div className={styles.listPane} data-testid="inbox-list-pane">
        <InboxList tenantId={tenantId} reloadKey={reloadKey} />
      </div>
      <div className={styles.detailPane} data-testid="inbox-detail-pane">
        {children}
      </div>
    </div>
  );
}

export function InboxShell({ tenantId, children }: { tenantId: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const basePath = `/t/${tenantId}/conversations`;

  if (pathname.startsWith(`${basePath}/templates`)) {
    return <>{children}</>;
  }

  return (
    <InboxRefreshProvider>
      <InboxShellContent tenantId={tenantId}>{children}</InboxShellContent>
    </InboxRefreshProvider>
  );
}
