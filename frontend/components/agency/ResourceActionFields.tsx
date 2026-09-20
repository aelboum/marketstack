"use client";

// Shared `resource`/`action` input pair for the delegation and deny
// forms (AccessDelegationPanel). The optional "fill from known
// permission" select sources from
// `lib/api/agency.ts::KNOWN_DELEGATABLE_PERMISSIONS` (real values, read
// from `product/agency/roles.py`) -- but is not exhaustive (there is no
// "list registered permissions" endpoint), so the two text fields below
// always stay directly editable, never locked to this list.
import { useId } from "react";
import { KNOWN_DELEGATABLE_PERMISSIONS } from "@/lib/api/agency";
import { Input } from "@/components/ui/Input";

export function ResourceActionFields({
  resource,
  action,
  onResourceChange,
  onActionChange,
}: {
  resource: string;
  action: string;
  onResourceChange: (value: string) => void;
  onActionChange: (value: string) => void;
}) {
  const selectId = useId();

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <label htmlFor={selectId} style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Fill from a known permission (optional)
        </label>
        <select
          id={selectId}
          value=""
          onChange={(event) => {
            const [selectedResource, selectedAction] = event.target.value.split(":");
            if (selectedResource && selectedAction) {
              onResourceChange(selectedResource);
              onActionChange(selectedAction);
            }
          }}
        >
          <option value="">Choose…</option>
          {KNOWN_DELEGATABLE_PERMISSIONS.map((permission) => (
            <option
              key={`${permission.resource}:${permission.action}`}
              value={`${permission.resource}:${permission.action}`}
            >
              {permission.label} ({permission.resource}:{permission.action})
            </option>
          ))}
        </select>
      </div>
      <Input
        label="Resource"
        required
        value={resource}
        onChange={(event) => onResourceChange(event.target.value)}
        placeholder="agency.client"
      />
      <Input
        label="Action"
        required
        value={action}
        onChange={(event) => onActionChange(event.target.value)}
        placeholder="read"
      />
    </>
  );
}
