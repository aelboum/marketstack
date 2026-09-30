"use client";

// Subscription lifecycle (`product/billing/routes.py`'s subscription
// routes). A tenant is not limited to one subscription by the backend
// schema (`core/billing/service.py::subscribe_idempotent()`'s own
// docstring: "nothing in this schema enforces at most one active
// subscription per tenant") -- this panel therefore always offers
// "create a subscription" alongside the existing list, rather than
// inventing a frontend one-subscription-per-tenant rule the backend does
// not itself enforce.
//
// Change-plan/cancel are only offered on a subscription whose own status
// is "active" -- not a duplicated authorization decision (the backend
// remains the sole authority on whether the call succeeds), just not
// offering a control whose own action is already a no-op/conflict for a
// subscription that is not currently active.
import { useState } from "react";
import {
  cancelSubscription,
  changeSubscriptionPlan,
  createSubscription,
  listAvailableResalePlans,
  listPlans,
  listSubscriptions,
  type Plan,
  type ResalePlan,
  type Subscription,
} from "@/lib/api/billing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

type PlanChoice = { platformPlanKey?: string; resalePlanId?: string };

/** Encodes a choice as one <select> value and back -- platform-plan keys
 * and resale-plan ids are both opaque strings from two different lists,
 * so the value alone cannot tell them apart without a tag. */
function encodeChoice(choice: PlanChoice): string {
  if (choice.platformPlanKey) return `platform:${choice.platformPlanKey}`;
  if (choice.resalePlanId) return `resale:${choice.resalePlanId}`;
  return "";
}

function decodeChoice(value: string): PlanChoice {
  if (value.startsWith("platform:")) return { platformPlanKey: value.slice("platform:".length) };
  if (value.startsWith("resale:")) return { resalePlanId: value.slice("resale:".length) };
  return {};
}

function PlanChoiceSelect({
  platformPlans,
  resalePlans,
  value,
  onChange,
  excludePlanKey,
}: {
  platformPlans: Plan[];
  resalePlans: ResalePlan[];
  value: string;
  onChange: (value: string) => void;
  /** The subscription's current plan, so change-plan does not offer the
   * plan it is already on. */
  excludePlanKey?: string | null;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
      <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Plan</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select a plan…</option>
        {platformPlans.length > 0 ? (
          <optgroup label="Platform plans">
            {platformPlans
              .filter((plan) => plan.key !== excludePlanKey)
              .map((plan) => (
                <option key={plan.key} value={encodeChoice({ platformPlanKey: plan.key })}>
                  {plan.name}
                </option>
              ))}
          </optgroup>
        ) : null}
        {resalePlans.length > 0 ? (
          <optgroup label="Available resale plans">
            {resalePlans.map((plan) => (
              <option key={plan.id} value={encodeChoice({ resalePlanId: plan.id })}>
                {plan.name} — {plan.price_amount} {plan.price_currency}/{plan.billing_interval}
              </option>
            ))}
          </optgroup>
        ) : null}
      </select>
    </label>
  );
}

/** Mounted only while its dialog is open (see `SubscriptionRow` below) --
 * so the two plan lists it needs are not fetched for every subscription
 * row up front, only when a user actually opens "Change plan". */
function ChangePlanDialog({
  tenantId,
  subscription,
  onClose,
  onChanged,
}: {
  tenantId: string;
  subscription: Subscription;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [choiceValue, setChoiceValue] = useState("");
  const platformPlansQuery = useApiQuery(() => listPlans(), []);
  const resalePlansQuery = useApiQuery(() => listAvailableResalePlans(tenantId), [tenantId]);
  const { run, state, reset } = useAsyncAction((choice: PlanChoice) =>
    changeSubscriptionPlan(tenantId, subscription.id, choice),
  );

  const choice = decodeChoice(choiceValue);
  const canSubmit = Boolean(choice.platformPlanKey || choice.resalePlanId);

  return (
    <Dialog
      open
      onClose={() => {
        reset();
        onClose();
      }}
      title="Change plan"
      description={`Choose a new plan for subscription ${subscription.plan_key ?? subscription.id}.`}
    >
      {platformPlansQuery.status === "loading" || resalePlansQuery.status === "loading" ? (
        <LoadingState label="Loading available plans…" />
      ) : platformPlansQuery.status === "error" ? (
        <ApiErrorPanel error={platformPlansQuery.error} onRetry={platformPlansQuery.refetch} />
      ) : resalePlansQuery.status === "error" ? (
        <ApiErrorPanel error={resalePlansQuery.error} onRetry={resalePlansQuery.refetch} />
      ) : (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (!canSubmit) return;
            const changed = await run(choice);
            if (changed) {
              onChanged();
              onClose();
            }
          }}
          style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
        >
          <PlanChoiceSelect
            platformPlans={platformPlansQuery.data}
            resalePlans={resalePlansQuery.data}
            value={choiceValue}
            onChange={setChoiceValue}
            excludePlanKey={subscription.plan_key}
          />
          {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)" }}>
            <Button type="button" variant="secondary" onClick={onClose} disabled={state.status === "pending"}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit || state.status === "pending"}>
              {state.status === "pending" ? "Changing…" : "Change plan"}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

function SubscriptionRow({
  tenantId,
  subscription,
  onChanged,
}: {
  tenantId: string;
  subscription: Subscription;
  onChanged: () => void;
}) {
  const [changePlanOpen, setChangePlanOpen] = useState(false);
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const { run: runCancel, state: cancelState } = useAsyncAction(() =>
    cancelSubscription(tenantId, subscription.id),
  );

  const isActive = subscription.status === "active";

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--space-2)", flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: "var(--font-size-md)" }}>
              {subscription.plan_key ?? "Unknown plan"}
            </h3>
            <Badge tone={isActive ? "success" : "neutral"}>{subscription.status}</Badge>
            {subscription.resale_plan_id ? <Badge tone="accent">Resale</Badge> : null}
          </div>
          <p style={{ margin: "var(--space-1) 0 0", fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
            Since {new Date(subscription.created_at).toLocaleDateString()}
          </p>
        </div>
        {isActive ? (
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <Button variant="secondary" size="sm" onClick={() => setChangePlanOpen(true)}>
              Change plan
            </Button>
            <Button variant="danger" size="sm" onClick={() => setConfirmCancelOpen(true)}>
              Cancel
            </Button>
          </div>
        ) : null}
      </div>

      {cancelState.status === "error" ? (
        <InlineNotice tone="danger">{cancelState.error.message}</InlineNotice>
      ) : null}

      {changePlanOpen ? (
        <ChangePlanDialog
          tenantId={tenantId}
          subscription={subscription}
          onClose={() => setChangePlanOpen(false)}
          onChanged={onChanged}
        />
      ) : null}

      <ConfirmDialog
        open={confirmCancelOpen}
        title="Cancel this subscription?"
        description="The backend records this subscription as cancelled. This UI makes no claim about exactly when access ends beyond what the resulting status reflects."
        confirmLabel="Cancel subscription"
        cancelLabel="Keep it"
        danger
        pending={cancelState.status === "pending"}
        onConfirm={async () => {
          await runCancel();
          setConfirmCancelOpen(false);
          onChanged();
        }}
        onCancel={() => setConfirmCancelOpen(false)}
      />
    </Card>
  );
}

function CreateSubscriptionForm({ tenantId, onCreated }: { tenantId: string; onCreated: () => void }) {
  const [choiceValue, setChoiceValue] = useState("");
  const platformPlansQuery = useApiQuery(() => listPlans(), []);
  const resalePlansQuery = useApiQuery(() => listAvailableResalePlans(tenantId), [tenantId]);
  const { run, state } = useAsyncAction((choice: PlanChoice) => createSubscription(tenantId, choice));

  if (platformPlansQuery.status === "loading" || resalePlansQuery.status === "loading") {
    return <LoadingState label="Loading available plans…" />;
  }
  if (platformPlansQuery.status === "error") {
    return <ApiErrorPanel error={platformPlansQuery.error} onRetry={platformPlansQuery.refetch} />;
  }
  if (resalePlansQuery.status === "error") {
    return <ApiErrorPanel error={resalePlansQuery.error} onRetry={resalePlansQuery.refetch} />;
  }

  const choice = decodeChoice(choiceValue);
  const canSubmit = Boolean(choice.platformPlanKey || choice.resalePlanId);

  if (platformPlansQuery.data.length === 0 && resalePlansQuery.data.length === 0) {
    return (
      <EmptyState
        title="No plans available to subscribe to"
        description="There is no platform plan or resale plan currently offered to this workspace."
      />
    );
  }

  return (
    <Card>
      <h3 style={{ marginTop: 0, fontSize: "var(--font-size-md)" }}>Start a subscription</h3>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!canSubmit) return;
          const created = await run(choice);
          if (created) {
            setChoiceValue("");
            onCreated();
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
      >
        <PlanChoiceSelect
          platformPlans={platformPlansQuery.data}
          resalePlans={resalePlansQuery.data}
          value={choiceValue}
          onChange={setChoiceValue}
        />
        {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
        <div>
          <Button type="submit" disabled={!canSubmit || state.status === "pending"}>
            {state.status === "pending" ? "Starting…" : "Subscribe"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function SubscriptionsPanel({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => listSubscriptions(tenantId), [tenantId]);

  if (query.status === "loading") return <LoadingState label="Loading subscriptions…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {query.data.length === 0 ? (
        <EmptyState title="No subscription yet" description="This workspace has no billing subscription." />
      ) : (
        query.data.map((subscription) => (
          <SubscriptionRow
            key={subscription.id}
            tenantId={tenantId}
            subscription={subscription}
            onChanged={query.refetch}
          />
        ))
      )}
      <CreateSubscriptionForm tenantId={tenantId} onCreated={query.refetch} />
    </div>
  );
}
