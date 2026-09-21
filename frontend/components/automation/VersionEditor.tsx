"use client";

// Edits a workflow's trigger + action step by writing a *draft* version.
//
// The durable engine only allows mutating a version while it is still a
// draft (`PUT .../versions/{id}` -- the backend itself refuses this once
// `status` is `"published"`, a 400). So there are exactly two cases,
// and this component is handed which one applies rather than guessing:
//   - `draftVersion` given -> overwrite it (`updateDraftVersion`);
//   - `draftVersion` omitted -> the current version is published (or
//     none exists yet) -> create a new draft (`createDraftVersion`),
//     seeded from `seedFrom` (the current published version, if any) so
//     editing feels like "change this" rather than "start over".
// Neither path invents a workflow-level edit endpoint -- both go through
// the version resource the backend actually exposes.
import { useState } from "react";
import {
  createDraftVersion,
  updateDraftVersion,
  type WorkflowVersion,
} from "@/lib/api/automation";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import {
  WorkflowStepFields,
  extractActionStep,
  initialStepFormValue,
  isStepFormComplete,
  stepFormValueToSteps,
} from "./WorkflowStepForm";

export function VersionEditor({
  tenantId,
  workflowId,
  draftVersion,
  seedFrom,
  onSaved,
}: {
  tenantId: string;
  workflowId: string;
  draftVersion?: WorkflowVersion | null;
  seedFrom?: WorkflowVersion | null;
  onSaved: (version: WorkflowVersion) => void;
}) {
  const seed = draftVersion ?? seedFrom ?? null;
  const [step, setStep] = useState(() =>
    initialStepFormValue(seed ? extractActionStep(seed) : null, seed?.trigger_type ?? null),
  );

  const { state, run } = useAsyncAction(() => {
    const input = stepFormValueToSteps(step);
    return draftVersion
      ? updateDraftVersion(tenantId, workflowId, draftVersion.id, input)
      : createDraftVersion(tenantId, workflowId, input);
  });

  const canSubmit = isStepFormComplete(step);

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const saved = await run();
        if (saved) onSaved(saved);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <WorkflowStepFields tenantId={tenantId} value={step} onChange={setStep} />

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending"
          ? "Saving…"
          : draftVersion
            ? "Save draft"
            : "Create new draft"}
      </Button>
    </form>
  );
}
