"use client";

// Wraps `POST /v1/agency/agencies/{agencyTenantId}/clients`. On success,
// calls `onCreated` so the caller (the clients list) refetches from the
// real API rather than optimistically inserting a client-shaped object
// of its own (docs/ROADMAP.md UI Track's mock-data policy, applied here:
// a completed UI-2 view uses the real API, never a frontend-invented
// stand-in for what the backend would have returned).
//
// docs/ROADMAP.md Phase 21 (Agency Provisioning Loop) adds the optional
// "apply an existing business setup" step -- fed by the agency's own
// real snapshots (`listSnapshots()`), never a fabricated list. There is
// no snapshot-authoring UI yet (Phase 21's own scope: compose the
// existing capability, not build one), so an agency with none simply
// does not see this step -- an honest empty state, not a dropdown with
// nothing useful in it.
import { useState } from "react";
import { createClient, type CreatedClient } from "@/lib/api/agency";
import { listSnapshots, type Snapshot } from "@/lib/api/templates";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { FormRow } from "@/components/ui/FormRow";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

function BusinessSetupField({
  agencyTenantId,
  snapshotId,
  onChange,
}: {
  agencyTenantId: string;
  snapshotId: string;
  onChange: (snapshotId: string) => void;
}) {
  const query = useApiQuery(() => listSnapshots(agencyTenantId), [agencyTenantId]);
  const snapshots: Snapshot[] = query.status === "success" ? query.data : [];

  if (query.status !== "success" || snapshots.length === 0) {
    // Loading, error, or genuinely none -- in every case, no step to
    // offer. A transient listSnapshots() failure must not block client
    // creation, which is why this is silent rather than an ApiErrorPanel.
    return null;
  }

  return (
    <div style={{ flexBasis: "100%" }}>
      <label
        htmlFor="business-setup-snapshot"
        style={{ display: "block", fontSize: "var(--font-size-sm)", marginBottom: "var(--space-1)" }}
      >
        Bedrijfsopzet toepassen (optioneel)
      </label>
      <select
        id="business-setup-snapshot"
        value={snapshotId}
        onChange={(event) => onChange(event.target.value)}
        style={{ fontSize: "var(--font-size-sm)", width: "100%", maxWidth: 320 }}
      >
        <option value="">Geen -- leeg klantbedrijf</option>
        {snapshots.map((snapshot) => (
          <option key={snapshot.id} value={snapshot.id}>
            {snapshot.name}
          </option>
        ))}
      </select>
    </div>
  );
}

export function CreateClientForm({
  agencyTenantId,
  onCreated,
}: {
  agencyTenantId: string;
  onCreated: (client: CreatedClient) => void;
}) {
  const [name, setName] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const { state, run } = useAsyncAction((clientName: string, chosenSnapshotId: string) =>
    createClient(agencyTenantId, clientName, chosenSnapshotId || undefined),
  );

  const created = state.status === "success" ? state.data : null;

  return (
    <FormRow
      onSubmit={async (event) => {
        event.preventDefault();
        if (!name.trim()) return;
        const result = await run(name.trim(), snapshotId);
        if (result) {
          setName("");
          setSnapshotId("");
          onCreated(result);
        }
      }}
    >
      <div style={{ flex: 1, minWidth: 200 }}>
        <Input
          label="Naam van het klantbedrijf"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Tandartspraktijk Acme"
        />
      </div>
      <BusinessSetupField
        agencyTenantId={agencyTenantId}
        snapshotId={snapshotId}
        onChange={setSnapshotId}
      />
      <Button type="submit" disabled={state.status === "pending" || !name.trim()}>
        {state.status === "pending" ? "Aanmaken…" : "Klantbedrijf aanmaken"}
      </Button>
      {state.status === "error" ? (
        <div style={{ flexBasis: "100%" }}>
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        </div>
      ) : null}
      {created?.provisioning_status === "setup_failed" ? (
        <div style={{ flexBasis: "100%" }}>
          <InlineNotice tone="warning">
            Klantbedrijf &quot;{created.name}&quot; is aangemaakt, maar de gekozen bedrijfsopzet kon
            niet worden toegepast. Het klantbedrijf is bruikbaar zonder deze configuratie.
          </InlineNotice>
        </div>
      ) : null}
    </FormRow>
  );
}
