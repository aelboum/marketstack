"use client";

// The `action_config` sub-form for whichever action type is currently
// selected. One component switching on `actionType` rather than five
// separate form components, because the five differ only in which
// fields they show -- the surrounding label/error/required treatment is
// identical, and a real, generic arbitrary-JSON editor is explicitly
// what the task tells this phase to avoid.
//
// Every field name and constraint here is read directly off
// `product/automation/actions.py`: `create_task` (title required,
// description optional), `update_contact` (all four fields optional --
// "a no-op update is a caller choice, not invalid", per that module's
// own comment), `move_opportunity` (to_stage_id required, must be a
// real stage id), `send_email` (to/subject/body all required),
// `send_webhook` (url required, https + public-host only). No field
// exists here that the backend does not also validate -- this is
// immediate UX feedback only; the backend stays authoritative, and every
// value still round-trips through it unmodified.
import { useState } from "react";
import { listPipelines, listStages, type Pipeline, type Stage } from "@/lib/api/crm";
import { MAX_ACTION_CONFIG_STRING_CHARS, type ActionType } from "@/lib/api/automation";
import { ACTION_TRIGGER_ID_NOTE } from "@/lib/automation/actions";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Input } from "@/components/ui/Input";
import { InlineNotice } from "@/components/ui/InlineNotice";

export type ActionConfigValue = Record<string, string>;

function TextField({
  label,
  value,
  onChange,
  required = false,
  type = "text",
  multiline = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  multiline?: boolean;
}) {
  const tooLong = value.length > MAX_ACTION_CONFIG_STRING_CHARS;
  const error = tooLong
    ? `Must be ${MAX_ACTION_CONFIG_STRING_CHARS.toLocaleString()} characters or fewer.`
    : undefined;

  if (multiline) {
    return (
      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          {label}
          {required ? " *" : ""}
        </span>
        <textarea
          required={required}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={3}
          aria-invalid={Boolean(error)}
          style={{
            fontFamily: "inherit",
            fontSize: "var(--font-size-sm)",
            padding: "var(--space-2)",
            border: `1px solid ${error ? "var(--color-danger)" : "var(--color-border-strong)"}`,
            borderRadius: "var(--radius-sm)",
          }}
        />
        {error ? <InlineNotice tone="danger">{error}</InlineNotice> : null}
      </label>
    );
  }

  return (
    <Input
      label={label}
      required={required}
      type={type}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      error={error}
    />
  );
}

function MoveOpportunityFields({
  tenantId,
  config,
  onChange,
}: {
  tenantId: string;
  config: ActionConfigValue;
  onChange: (config: ActionConfigValue) => void;
}) {
  const pipelinesQuery = useApiQuery(() => listPipelines(tenantId), [tenantId]);
  const [pipelineId, setPipelineId] = useState("");
  const stagesQuery = useApiQuery(
    () => (pipelineId ? listStages(tenantId, pipelineId) : Promise.resolve<Stage[]>([])),
    [tenantId, pipelineId],
  );

  const pipelines: Pipeline[] = pipelinesQuery.status === "success" ? pipelinesQuery.data : [];
  const stages: Stage[] = stagesQuery.status === "success" ? stagesQuery.data : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Pipeline
        </span>
        <select
          value={pipelineId}
          onChange={(event) => {
            setPipelineId(event.target.value);
            onChange({ ...config, to_stage_id: "" });
          }}
        >
          <option value="">Select a pipeline…</option>
          {pipelines.map((pipeline) => (
            <option key={pipeline.id} value={pipeline.id}>
              {pipeline.name}
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Target stage *
        </span>
        <select
          required
          value={config.to_stage_id ?? ""}
          onChange={(event) => onChange({ ...config, to_stage_id: event.target.value })}
          disabled={!pipelineId}
        >
          <option value="">{pipelineId ? "Select a stage…" : "Choose a pipeline first"}</option>
          {stages.map((stage) => (
            <option key={stage.id} value={stage.id}>
              {stage.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

export function ActionConfigFields({
  tenantId,
  actionType,
  config,
  onChange,
}: {
  tenantId: string;
  actionType: ActionType;
  config: ActionConfigValue;
  onChange: (config: ActionConfigValue) => void;
}) {
  const set = (key: string) => (value: string) => onChange({ ...config, [key]: value });
  const note = ACTION_TRIGGER_ID_NOTE[actionType];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {note ? <InlineNotice tone="neutral">{note}</InlineNotice> : null}

      {actionType === "create_task" ? (
        <>
          <TextField label="Title" required value={config.title ?? ""} onChange={set("title")} />
          <TextField
            label="Description"
            value={config.description ?? ""}
            onChange={set("description")}
            multiline
          />
        </>
      ) : null}

      {actionType === "update_contact" ? (
        <>
          <TextField
            label="First name"
            value={config.first_name ?? ""}
            onChange={set("first_name")}
          />
          <TextField label="Last name" value={config.last_name ?? ""} onChange={set("last_name")} />
          <TextField label="Email" type="email" value={config.email ?? ""} onChange={set("email")} />
          <TextField label="Phone" value={config.phone ?? ""} onChange={set("phone")} />
        </>
      ) : null}

      {actionType === "move_opportunity" ? (
        <MoveOpportunityFields tenantId={tenantId} config={config} onChange={onChange} />
      ) : null}

      {actionType === "send_email" ? (
        <>
          <TextField label="To" required type="email" value={config.to ?? ""} onChange={set("to")} />
          <TextField label="Subject" required value={config.subject ?? ""} onChange={set("subject")} />
          <TextField label="Body" required value={config.body ?? ""} onChange={set("body")} multiline />
        </>
      ) : null}

      {actionType === "send_webhook" ? (
        <>
          <TextField label="URL" required type="url" value={config.url ?? ""} onChange={set("url")} />
          <p
            style={{
              margin: 0,
              fontSize: "var(--font-size-xs)",
              color: "var(--color-text-muted)",
            }}
          >
            Must be an https URL on a public host -- the backend refuses a private, loopback, or
            internal address.
          </p>
        </>
      ) : null}
    </div>
  );
}

/** Whether `config` satisfies the *required* fields for `actionType`.
 * Client-side only, for disabling submit until the obviously-incomplete
 * case is fixed -- the backend's own validation is still what actually
 * decides, and its message is shown verbatim on a 400. */
export function isActionConfigComplete(actionType: ActionType, config: ActionConfigValue): boolean {
  switch (actionType) {
    case "create_task":
      return Boolean(config.title?.trim());
    case "update_contact":
      return true;
    case "move_opportunity":
      return Boolean(config.to_stage_id?.trim());
    case "send_email":
      return Boolean(config.to?.trim() && config.subject?.trim() && config.body?.trim());
    case "send_webhook":
      return Boolean(config.url?.trim());
    default:
      return false;
  }
}

/** Strips blank optional fields before submit -- the backend treats an
 * absent key and an empty string differently for some actions (a blank
 * `update_contact` field is a real no-op, but there is no reason to send
 * keys the user never touched). */
export function cleanActionConfig(config: ActionConfigValue): Record<string, string> {
  const cleaned: Record<string, string> = {};
  for (const [key, value] of Object.entries(config)) {
    if (value.trim().length > 0) cleaned[key] = value;
  }
  return cleaned;
}
