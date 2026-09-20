"use client";

// Custom field values for one contact/company/opportunity
// (`product/crm/custom_fields.py`, Phase 4.4). Defining a new field
// (`crm.custom_field_definition:create`) is owner-only server-side; this
// panel still offers the control and lets a real 403/404 explain itself,
// same discipline as TagsPanel.
import { useState } from "react";
import {
  defineField,
  getFieldValues,
  listFieldDefinitions,
  setFieldValue,
  type EntityType,
  type FieldType,
} from "@/lib/api/crm";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

function FieldValueForm({
  tenantId,
  entityType,
  entityId,
  fieldDefinitionId,
  fieldType,
  currentValue,
  onSaved,
}: {
  tenantId: string;
  entityType: EntityType;
  entityId: string;
  fieldDefinitionId: string;
  fieldType: FieldType;
  currentValue: string | number | boolean | null;
  onSaved: () => void;
}) {
  const [value, setValue] = useState(currentValue == null ? "" : String(currentValue));
  const { state, run } = useAsyncAction(() => {
    const coerced: string | number | boolean =
      fieldType === "number" ? Number(value) : fieldType === "boolean" ? value === "true" : value;
    return setFieldValue(tenantId, entityType, entityId, fieldDefinitionId, coerced);
  });

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        const saved = await run();
        if (saved) onSaved();
      }}
      style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}
    >
      {fieldType === "boolean" ? (
        <select value={value} onChange={(event) => setValue(event.target.value)}>
          <option value="">—</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      ) : (
        <div style={{ flex: 1 }}>
          <Input
            label="Value"
            type={fieldType === "number" ? "number" : fieldType === "date" ? "date" : "text"}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </div>
      )}
      <Button type="submit" size="sm" disabled={state.status === "pending"}>
        Save
      </Button>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </form>
  );
}

function DefineFieldForm({
  tenantId,
  entityType,
  onDefined,
}: {
  tenantId: string;
  entityType: EntityType;
  onDefined: () => void;
}) {
  const [name, setName] = useState("");
  const [fieldType, setFieldType] = useState<FieldType>("text");
  const { state, run } = useAsyncAction(() => defineField(tenantId, { entity_type: entityType, name, field_type: fieldType }));

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!name.trim()) return;
        const created = await run();
        if (created) {
          setName("");
          onDefined();
        }
      }}
      style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}
    >
      <div style={{ flex: 1, minWidth: 160 }}>
        <Input
          label="New field name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. lead_source"
        />
      </div>
      <select value={fieldType} onChange={(event) => setFieldType(event.target.value as FieldType)}>
        <option value="text">Text</option>
        <option value="number">Number</option>
        <option value="date">Date</option>
        <option value="boolean">Yes/No</option>
      </select>
      <Button type="submit" size="sm" disabled={state.status === "pending" || !name.trim()}>
        Define field
      </Button>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </form>
  );
}

export function CustomFieldsPanel({
  tenantId,
  entityType,
  entityId,
}: {
  tenantId: string;
  entityType: EntityType;
  entityId: string;
}) {
  const definitionsQuery = useApiQuery(
    () => listFieldDefinitions(tenantId, entityType),
    [tenantId, entityType],
  );
  const valuesQuery = useApiQuery(
    () => getFieldValues(tenantId, entityType, entityId),
    [tenantId, entityType, entityId],
  );

  if (definitionsQuery.status === "loading" || valuesQuery.status === "loading") {
    return <LoadingState label="Loading custom fields…" />;
  }
  if (definitionsQuery.status === "error") {
    return <ApiErrorPanel error={definitionsQuery.error} onRetry={definitionsQuery.refetch} />;
  }
  if (valuesQuery.status === "error") {
    return <ApiErrorPanel error={valuesQuery.error} onRetry={valuesQuery.refetch} />;
  }

  const valueByDefinitionId = new Map(valuesQuery.data.map((v) => [v.field_definition_id, v.value]));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {definitionsQuery.data.length === 0 ? (
        <p style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-faint)" }}>
          No custom fields defined for {entityType}s yet.
        </p>
      ) : (
        definitionsQuery.data.map((definition) => (
          <div key={definition.id} style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
              {definition.name}
            </span>
            <FieldValueForm
              tenantId={tenantId}
              entityType={entityType}
              entityId={entityId}
              fieldDefinitionId={definition.id}
              fieldType={definition.field_type}
              currentValue={valueByDefinitionId.get(definition.id) ?? null}
              onSaved={valuesQuery.refetch}
            />
          </div>
        ))
      )}

      <DefineFieldForm tenantId={tenantId} entityType={entityType} onDefined={definitionsQuery.refetch} />
    </div>
  );
}
