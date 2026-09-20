"use client";

// Conversations inbox (UI-4, replaces the UI-1 placeholder).
import { useState } from "react";
import Link from "next/link";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ThreadsList, CreateThreadForm } from "@/components/conversations";

export default function ConversationsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Conversations"
        actions={
          <>
            <Link href={`/t/${tenantId}/conversations/templates`}>
              <Button variant="secondary">Templates</Button>
            </Link>
            <Button onClick={() => setCreateOpen(true)}>New conversation</Button>
          </>
        }
      />
      <ThreadsList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={<Button size="sm" onClick={() => setCreateOpen(true)}>Start a conversation</Button>}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New conversation">
        <CreateThreadForm
          tenantId={tenantId}
          onSaved={() => {
            setCreateOpen(false);
            setReloadKey((key) => key + 1);
          }}
        />
      </Dialog>
    </Page>
  );
}
