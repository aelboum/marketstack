"use client";

// The trigger + single-action-step fields shared by "create a workflow"
// and "edit a draft version". Both ultimately produce the same
// `{start_step_key, steps, trigger_type, trigger_config}` shape this UI
// always writes (see lib/api/automation.ts's module docstring) -- this
// component is the one place that shape gets built, so the two callers
// cannot drift.
import {
  ACTION_TYPES,
  TRIGGER_TYPES,
  type ActionStep,
  type ActionType,
  type TriggerType,
  type WorkflowVersion,
} from "@/lib/api/automation";
import { ACTION_LABELS, TRIGGER_LABELS } from "@/lib/automation/actions";
import {
  ActionConfigFields,
  cleanActionConfig,
  isActionConfigComplete,
  type ActionConfigValue,
} from "./ActionConfigFields";

const STEP_KEY = "action";

export type WorkflowStepFormValue = {
  triggerType: TriggerType | "";
  actionType: ActionType;
  config: ActionConfigValue;
};

/** The single action step this UI ever creates, extracted back out of a
 * version's `steps` -- `null` if the version's start step is not an
 * action step this UI built (a condition/delay/wait_for_event node, or
 * a richer graph from outside this UI). See module docstring on
 * lib/api/automation.ts. */
export function extractActionStep(version: WorkflowVersion): ActionStep | null {
  const start = version.steps.find((step) => step.step_key === version.start_step_key);
  if (!start || start.type !== "action") return null;
  return start as ActionStep;
}

export function initialStepFormValue(
  fromStep?: ActionStep | null,
  fromTriggerType?: TriggerType | null,
): WorkflowStepFormValue {
  return {
    triggerType: fromTriggerType ?? "",
    actionType: fromStep?.action_type ?? "create_task",
    config: fromStep?.action_config ?? {},
  };
}

export function stepFormValueToSteps(value: WorkflowStepFormValue): {
  start_step_key: string;
  steps: ActionStep[];
  trigger_type: TriggerType | null;
} {
  return {
    start_step_key: STEP_KEY,
    steps: [
      {
        step_key: STEP_KEY,
        type: "action",
        action_type: value.actionType,
        action_config: cleanActionConfig(value.config),
        next_step_key: null,
      },
    ],
    trigger_type: value.triggerType || null,
  };
}

export function isStepFormComplete(value: WorkflowStepFormValue): boolean {
  return isActionConfigComplete(value.actionType, value.config);
}

export function WorkflowStepFields({
  tenantId,
  value,
  onChange,
}: {
  tenantId: string;
  value: WorkflowStepFormValue;
  onChange: (value: WorkflowStepFormValue) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Trigger (optional -- leave blank to start runs manually only)
        </span>
        <select
          value={value.triggerType}
          onChange={(event) =>
            onChange({ ...value, triggerType: event.target.value as TriggerType | "" })
          }
        >
          <option value="">No automatic trigger</option>
          {TRIGGER_TYPES.map((trigger) => (
            <option key={trigger} value={trigger}>
              {TRIGGER_LABELS[trigger]}
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Action
        </span>
        <select
          value={value.actionType}
          onChange={(event) =>
            onChange({ ...value, actionType: event.target.value as ActionType, config: {} })
          }
        >
          {ACTION_TYPES.map((action) => (
            <option key={action} value={action}>
              {ACTION_LABELS[action]}
            </option>
          ))}
        </select>
      </label>

      <ActionConfigFields
        tenantId={tenantId}
        actionType={value.actionType}
        config={value.config}
        onChange={(config) => onChange({ ...value, config })}
      />
    </div>
  );
}
