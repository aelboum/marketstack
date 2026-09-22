"use client";

// Automation hub (UI-10). `lib/nav/config.ts` already listed
// "Automation" as a planned nav item with no route -- this is that
// route.
//
// Built against the durable engine only (`/v1/automation/durable`) --
// see lib/api/automation.ts's module docstring for why. There is no
// sub-navigation here: unlike CRM/Marketing/Appointments, this domain
// has exactly one entity type (workflows; runs are always reached
// through the workflow that owns them, matching the real API's own
// nesting), so a sub-nav would exist only to switch between one thing.
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { WorkflowsList, CreateWorkflowForm } from "@/components/automation";

export default function AutomationPage() {
  const { tenantId } = useTenant();
  const [createOpen, setCreateOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Automatisering"
        description="Automatically act when something happens in your business."
        actions={<Button onClick={() => setCreateOpen(true)}>New automation</Button>}
      />
      <WorkflowsList
        tenantId={tenantId}
        reloadKey={reloadKey}
        onCreate={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            Create an automation
          </Button>
        }
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New automation">
        <CreateWorkflowForm
          tenantId={tenantId}
          onCreated={() => {
            setCreateOpen(false);
            setReloadKey((key) => key + 1);
          }}
        />
      </Dialog>
    </Page>
  );
}
