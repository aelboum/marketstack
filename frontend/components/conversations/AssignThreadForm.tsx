"use client";

// `assign_thread()` requires a real `TenantMembership` for the assignee
// (`product/conversations/threads.py`'s own IDOR-adjacent check) -- but
// there is still no "list tenant members" endpoint anywhere in this
// product's API (the same documented gap UI-2's delegation forms
// already flagged), so this is a raw user-id input, not a picker.
import { useState } from "react";
import { assignThread, type Thread } from "@/lib/api/conversations";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function AssignThreadForm({
  tenantId,
  threadId,
  currentAssigneeUserId,
  onAssigned,
}: {
  tenantId: string;
  threadId: string;
  currentAssigneeUserId: string | null;
  onAssigned: (thread: Thread) => void;
}) {
  const [assigneeUserId, setAssigneeUserId] = useState("");
  const { state, run } = useAsyncAction(() => assignThread(tenantId, threadId, assigneeUserId.trim()));

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!assigneeUserId.trim()) return;
        const updated = await run();
        if (updated) onAssigned(updated);
      }}
      style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}
    >
      <div style={{ flex: 1, minWidth: 220 }}>
        <Input
          label="Assign to user ID"
          value={assigneeUserId}
          onChange={(event) => setAssigneeUserId(event.target.value)}
          placeholder={currentAssigneeUserId ?? "00000000-0000-0000-0000-000000000000"}
        />
      </div>
      <Button type="submit" size="sm" disabled={state.status === "pending" || !assigneeUserId.trim()}>
        {state.status === "pending" ? "Assigning…" : "Assign"}
      </Button>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </form>
  );
}
