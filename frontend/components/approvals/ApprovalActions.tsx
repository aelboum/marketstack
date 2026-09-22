"use client";

// Approve/reject/execute (docs/ROADMAP.md Phase 29). Every action calls
// the real backend route, which itself calls the real
// `control_plane.approvals` function -- never a local state transition.
//
// **Authorization is never assumed here.** Buttons render based on
// `Approval.can_decide`/`can_execute` -- *state* flags only ("is this
// approval still pending/approved"), never a claim about whether the
// current user is allowed to act. A user without the real backend
// permission still sees the button and still gets a real 403/404 from a
// real click, exactly per the product's own "backend is the sole
// authorization authority" rule -- this component never hides a button
// to fake an authorization decision it cannot actually make.
//
// **Stale/conflict handling**: a 409 (someone else already decided/
// executed this approval, or a double-click raced) is detected via
// `ApiError.status` directly, not the coarse `kind` taxonomy
// (`lib/api/errors.ts` has no dedicated "conflict" kind, and adding one
// would be a cross-cutting change to every module's shared error client
// -- out of this phase's own scope) -- shown as its own distinct,
// business-language notice, then the parent view is refetched so the
// screen reflects the real current state rather than staying stale.
import { useEffect, useState } from "react";
import {
  approveApproval,
  executeApproval,
  rejectApproval,
  type Approval,
} from "@/lib/api/approvals";
import type { ApiError } from "@/lib/api/errors";
import { useAsyncAction, type AsyncActionState } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

type PendingConfirmation = "approve" | "reject" | "execute" | null;

const STALE_MESSAGE =
  "Deze goedkeuring is niet meer actueel -- iemand anders heeft deze mogelijk al " +
  "beoordeeld of uitgevoerd. De gegevens zijn bijgewerkt.";

/** Reacts to `state` transitions rather than reading `state` right after
 * calling `run()` -- a plain object returned by `useAsyncAction()` is a
 * snapshot from the render that created the closure calling `run()`;
 * `run()`'s own internal `setState` only becomes visible on the *next*
 * render, so inspecting `.state` synchronously in the same function that
 * called `run()` sees the stale, pre-call value, not the resolved one.
 * An effect keyed on `state` itself always sees the real, current value. */
function useActionOutcome(
  state: AsyncActionState<Approval>,
  handlers: { onSuccess: () => void; onConflict: () => void },
) {
  useEffect(() => {
    if (state.status === "success") {
      handlers.onSuccess();
    } else if (state.status === "error" && state.error.status === 409) {
      handlers.onConflict();
    }
    // Only re-run when `state` itself actually changes -- `handlers` is a
    // fresh object every render and must not retrigger this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);
}

export function ApprovalActions({
  tenantId,
  approval,
  onChanged,
}: {
  tenantId: string;
  approval: Approval;
  onChanged: () => void;
}) {
  const [confirming, setConfirming] = useState<PendingConfirmation>(null);
  const [staleNotice, setStaleNotice] = useState(false);

  const approveAction = useAsyncAction(() => approveApproval(tenantId, approval.id));
  const rejectAction = useAsyncAction(() => rejectApproval(tenantId, approval.id));
  const executeAction = useAsyncAction(() => executeApproval(tenantId, approval.id));

  const onOutcome = { onSuccess: onChanged, onConflict: () => (setStaleNotice(true), onChanged()) };
  useActionOutcome(approveAction.state, onOutcome);
  useActionOutcome(rejectAction.state, onOutcome);
  useActionOutcome(executeAction.state, onOutcome);

  const activeAction =
    confirming === "approve" ? approveAction : confirming === "reject" ? rejectAction : executeAction;

  async function handleConfirm() {
    setStaleNotice(false);
    await activeAction.run();
    setConfirming(null);
  }

  if (!approval.can_decide && !approval.can_execute) {
    return null;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {staleNotice ? <InlineNotice tone="warning">{STALE_MESSAGE}</InlineNotice> : null}

      {approval.can_decide ? (
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button onClick={() => setConfirming("approve")}>Goedkeuren</Button>
          <Button variant="danger" onClick={() => setConfirming("reject")}>
            Afwijzen
          </Button>
        </div>
      ) : null}

      {approval.can_execute ? (
        <div>
          <Button onClick={() => setConfirming("execute")}>Uitvoeren</Button>
        </div>
      ) : null}

      {(["approve", "reject", "execute"] as const).map((kind) => {
        const action = kind === "approve" ? approveAction : kind === "reject" ? rejectAction : executeAction;
        return action.state.status === "error" && action.state.error.status !== 409 ? (
          <InlineNotice key={kind} tone="danger">
            {describeError(kind, action.state.error)}
          </InlineNotice>
        ) : null;
      })}

      <ConfirmDialog
        open={confirming !== null}
        title={confirmTitle(confirming)}
        description={confirmDescription(confirming)}
        confirmLabel={confirmLabel(confirming)}
        danger={confirming === "reject"}
        pending={activeAction.isPending}
        onConfirm={handleConfirm}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}

function confirmTitle(kind: PendingConfirmation): string {
  switch (kind) {
    case "approve":
      return "Actie goedkeuren?";
    case "reject":
      return "Actie afwijzen?";
    case "execute":
      return "Actie nu uitvoeren?";
    default:
      return "";
  }
}

function confirmDescription(kind: PendingConfirmation): string {
  switch (kind) {
    case "approve":
      return "Na goedkeuring kan de actie worden uitgevoerd. Dit wijzigt de status blijvend.";
    case "reject":
      return "Een afgewezen actie kan niet meer worden uitgevoerd. Dit wijzigt de status blijvend.";
    case "execute":
      return "De actie wordt nu daadwerkelijk uitgevoerd.";
    default:
      return "";
  }
}

function confirmLabel(kind: PendingConfirmation): string {
  switch (kind) {
    case "approve":
      return "Goedkeuren";
    case "reject":
      return "Afwijzen";
    case "execute":
      return "Uitvoeren";
    default:
      return "Bevestigen";
  }
}

function describeError(kind: "approve" | "reject" | "execute", error: ApiError): string {
  if (error.kind === "forbidden") {
    return "U bent niet bevoegd om deze actie uit te voeren.";
  }
  return error.message;
}
