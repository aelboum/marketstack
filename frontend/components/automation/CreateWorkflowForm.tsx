"use client";

// Creates a workflow -- `POST .../durable/tenants/{t}/workflows`. The
// backend creates the `Workflow` identity and its first version (draft,
// `version_number: 1`) atomically and returns both; this form hands the
// caller that whole response so the detail page can go straight there.
import { useState } from "react";
import { createWorkflow, type Workflow, type WorkflowVersion } from "@/lib/api/automation";
import { MAX_WORKFLOW_NAME_LENGTH } from "@/lib/automation/constraints";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import {
  WorkflowStepFields,
  initialStepFormValue,
  isStepFormComplete,
  stepFormValueToSteps,
} from "./WorkflowStepForm";

export function CreateWorkflowForm({
  tenantId,
  onCreated,
}: {
  tenantId: string;
  onCreated: (result: { workflow: Workflow; version: WorkflowVersion }) => void;
}) {
  const [name, setName] = useState("");
  const [step, setStep] = useState(() => initialStepFormValue());

  const { state, run } = useAsyncAction(() =>
    createWorkflow(tenantId, { name, ...stepFormValueToSteps(step) }),
  );

  const nameTooLong = name.length > MAX_WORKFLOW_NAME_LENGTH;
  const canSubmit = name.trim().length > 0 && !nameTooLong && isStepFormComplete(step);

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const created = await run();
        if (created) onCreated(created);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Name"
        required
        value={name}
        onChange={(event) => setName(event.target.value)}
        error={nameTooLong ? `Name must be ${MAX_WORKFLOW_NAME_LENGTH} characters or fewer.` : undefined}
      />

      <WorkflowStepFields tenantId={tenantId} value={step} onChange={setStep} />

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Creating…" : "Create automation"}
      </Button>
    </form>
  );
}
