"use client";

import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { CrmSubNav, ContactsList, ContactForm, ImportExportPanel } from "@/components/crm";

export default function ContactsPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [importExportOpen, setImportExportOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Contacts"
        actions={
          <>
            <Button variant="secondary" onClick={() => setImportExportOpen(true)}>
              Import / Export
            </Button>
            <Button onClick={() => setCreateOpen(true)}>New contact</Button>
          </>
        }
      />
      <CrmSubNav tenantId={tenantId} />
      <ContactsList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={<Button size="sm" onClick={() => setCreateOpen(true)}>Create a contact</Button>}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New contact">
        <ContactForm
          tenantId={tenantId}
          onSaved={() => {
            setCreateOpen(false);
            setReloadKey((key) => key + 1);
          }}
        />
      </Dialog>
      <Dialog open={importExportOpen} onClose={() => setImportExportOpen(false)} title="Import / export contacts">
        <ImportExportPanel tenantId={tenantId} />
      </Dialog>
    </Page>
  );
}
