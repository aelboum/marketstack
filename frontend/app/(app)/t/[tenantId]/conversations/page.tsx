"use client";

// The Unified Inbox (docs/ROADMAP.md Phase 30) -- "Inbox" in the
// business-oriented navigation (lib/nav/config.ts already points here;
// this route was not renamed). The real list now lives in
// `InboxShell`'s persistent left pane (layout.tsx); this page is what
// renders on the right when no thread is selected yet -- on a narrow
// viewport it is hidden entirely in favor of the list itself
// (InboxShell.module.css), exactly the conventional inbox interaction
// docs/ROADMAP.md Phase 30 asks for.
import { useState } from "react";
import Link from "next/link";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/states";
import { CreateThreadForm, useInboxRefresh } from "@/components/conversations";

export default function ConversationsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const { refresh } = useInboxRefresh();

  return (
    <Page>
      <PageHeader
        title="Inbox"
        actions={
          <>
            <Link href={`/t/${tenantId}/conversations/templates`}>
              <Button variant="secondary">Berichtsjablonen</Button>
            </Link>
            <Button onClick={() => setCreateOpen(true)}>Nieuw gesprek</Button>
          </>
        }
      />
      <EmptyState
        title="Selecteer een gesprek"
        description="Kies links een gesprek om de details en berichten te bekijken."
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="Nieuw gesprek">
        <CreateThreadForm
          tenantId={tenantId}
          onSaved={() => {
            setCreateOpen(false);
            refresh();
          }}
        />
      </Dialog>
    </Page>
  );
}
