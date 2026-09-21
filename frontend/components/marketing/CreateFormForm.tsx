"use client";

// Create a form with a dynamic set of field definitions
// (`name`/`field_type`/`required`) -- matches `CreateFormRequest`
// exactly (`product/marketing/routes.py`). No edit endpoint exists, so
// this is the only place these definitions are ever set.
import { useState } from "react";
import { createForm, FORM_FIELD_TYPES, type FormFieldDefinition, type FormFieldType } from "@/lib/api/marketing";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

const EMPTY_FIELD: FormFieldDefinition = { name: "", field_type: "text", required: false };

export function CreateFormForm({ tenantId, onSaved }: { tenantId: string; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [fields, setFields] = useState<FormFieldDefinition[]>([{ ...EMPTY_FIELD }]);

  const { state, run } = useAsyncAction(() =>
    createForm(tenantId, { name, fields: fields.filter((f) => f.name.trim()) }),
  );

  const canSubmit = name.trim().length > 0 && fields.some((f) => f.name.trim());

  function updateField(index: number, patch: Partial<FormFieldDefinition>) {
    setFields((current) => current.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  }

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const saved = await run();
        if (saved) {
          setName("");
          setFields([{ ...EMPTY_FIELD }]);
          onSaved();
        }
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input label="Form name" required value={name} onChange={(event) => setName(event.target.value)} />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Fields</span>
        {fields.map((field, index) => (
          <div key={index} style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
            <input
              aria-label={`Field ${index + 1} name`}
              value={field.name}
              onChange={(event) => updateField(index, { name: event.target.value })}
              placeholder="Field name"
              style={{ flex: 1, padding: "var(--space-2)", border: "1px solid var(--color-border-strong)", borderRadius: "var(--radius-sm)" }}
            />
            <select
              aria-label={`Field ${index + 1} type`}
              value={field.field_type}
              onChange={(event) => updateField(index, { field_type: event.target.value as FormFieldType })}
            >
              {FORM_FIELD_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <label style={{ display: "flex", alignItems: "center", gap: "var(--space-1)", fontSize: "var(--font-size-xs)" }}>
              <input
                type="checkbox"
                checked={field.required}
                onChange={(event) => updateField(index, { required: event.target.checked })}
              />
              Required
            </label>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setFields((current) => current.filter((_, i) => i !== index))}
              disabled={fields.length === 1}
            >
              Remove
            </Button>
          </div>
        ))}
        <Button type="button" variant="secondary" size="sm" onClick={() => setFields((current) => [...current, { ...EMPTY_FIELD }])}>
          Add field
        </Button>
      </div>

      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Creating…" : "Create form"}
      </Button>
    </form>
  );
}
