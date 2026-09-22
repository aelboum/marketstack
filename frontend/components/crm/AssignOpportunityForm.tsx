"use client";

// docs/ROADMAP.md Phase 22 -- `assign_opportunity()` requires a real
// `TenantMembership` for the assignee (`product/crm/opportunities.py`'s
// own IDOR-adjacent check) -- but there is still no "list tenant
// members" endpoint anywhere in this product's API (the identical,
// already-documented gap `components/conversations/AssignThreadForm.tsx`
// names for its own assignment problem), so this is a raw user-id input,
// not a picker.
import { useState } from "react";
import { assignOpportunity, type Opportunity } from "@/lib/api/crm";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { FormRow } from "@/components/ui/FormRow";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function AssignOpportunityForm({
  tenantId,
  opportunityId,
  currentAssignedUserId,
  onAssigned,
}: {
  tenantId: string;
  opportunityId: string;
  currentAssignedUserId: string | null;
  onAssigned: (opportunity: Opportunity) => void;
}) {
  const [assignedUserId, setAssignedUserId] = useState("");
  const { state, run } = useAsyncAction((value: string | null) =>
    assignOpportunity(tenantId, opportunityId, value),
  );

  return (
    <FormRow
      onSubmit={async (event) => {
        event.preventDefault();
        if (!assignedUserId.trim()) return;
        const updated = await run(assignedUserId.trim());
        if (updated) onAssigned(updated);
      }}
    >
      <div style={{ flex: 1, minWidth: 220 }}>
        <Input
          label="Toewijzen aan gebruikers-ID"
          value={assignedUserId}
          onChange={(event) => setAssignedUserId(event.target.value)}
          placeholder={currentAssignedUserId ?? "00000000-0000-0000-0000-000000000000"}
        />
      </div>
      <Button type="submit" size="sm" disabled={state.status === "pending" || !assignedUserId.trim()}>
        {state.status === "pending" ? "Toewijzen…" : "Toewijzen"}
      </Button>
      {currentAssignedUserId ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={state.status === "pending"}
          onClick={async () => {
            const updated = await run(null);
            if (updated) onAssigned(updated);
          }}
        >
          Toewijzing intrekken
        </Button>
      ) : null}
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </FormRow>
  );
}
