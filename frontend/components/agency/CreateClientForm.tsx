"use client";

// Wraps `POST /v1/agency/agencies/{agencyTenantId}/clients`. On success,
// calls `onCreated` so the caller (the clients list) refetches from the
// real API rather than optimistically inserting a client-shaped object
// of its own (docs/ROADMAP.md UI Track's mock-data policy, applied here:
// a completed UI-2 view uses the real API, never a frontend-invented
// stand-in for what the backend would have returned).
import { useState } from "react";
import { createClient, type CreatedClient } from "@/lib/api/agency";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { FormRow } from "@/components/ui/FormRow";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CreateClientForm({
  agencyTenantId,
  onCreated,
}: {
  agencyTenantId: string;
  onCreated: (client: CreatedClient) => void;
}) {
  const [name, setName] = useState("");
  const { state, run, reset } = useAsyncAction((clientName: string) =>
    createClient(agencyTenantId, clientName),
  );

  return (
    <FormRow
      onSubmit={async (event) => {
        event.preventDefault();
        if (!name.trim()) return;
        const created = await run(name.trim());
        if (created) {
          setName("");
          reset();
          onCreated(created);
        }
      }}
    >
      <div style={{ flex: 1, minWidth: 200 }}>
        <Input
          label="New client name"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Acme Dental"
        />
      </div>
      <Button type="submit" disabled={state.status === "pending" || !name.trim()}>
        {state.status === "pending" ? "Creating…" : "Create client"}
      </Button>
      {state.status === "error" ? (
        <div style={{ flexBasis: "100%" }}>
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        </div>
      ) : null}
    </FormRow>
  );
}
