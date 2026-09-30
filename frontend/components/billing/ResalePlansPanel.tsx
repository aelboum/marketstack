"use client";

// A reseller tenant's own resale-plan catalog
// (`product/billing/routes.py`'s resale-plan routes). Mirrors
// components/marketing/TemplatesPanel.tsx's own row/create-form shape.
//
// `price_amount`/`price_currency`/`billing_interval` are set once at
// creation and have no PATCH field on the backend
// (`UpdateResalePlanRequest` only carries `name`/`description`) -- so,
// unlike the create form, the edit form here offers only those two
// fields; that is a real backend limitation, not an omission.
//
// A 403/404 from any of these calls (this tenant may not manage resale
// plans, or the resale plan is not theirs) surfaces through the same
// `ApiErrorPanel`/`ApiError` "forbidden" classification every other
// module already uses -- no frontend permission check is layered on top.
import { useState } from "react";
import {
  createResalePlan,
  deactivateResalePlan,
  listResalePlans,
  updateResalePlan,
  RESALE_PLAN_STATUS_ENABLED,
  type ResalePlan,
} from "@/lib/api/billing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { FormRow, FormRowGrow } from "@/components/ui/FormRow";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

const BILLING_INTERVALS = ["month", "year"] as const;

function priceLabel(plan: ResalePlan): string {
  return `${plan.price_amount} ${plan.price_currency} / ${plan.billing_interval}`;
}

function ResalePlanRow({
  tenantId,
  plan,
  onChanged,
}: {
  tenantId: string;
  plan: ResalePlan;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(plan.name);
  const [description, setDescription] = useState(plan.description ?? "");
  const [confirmDeactivateOpen, setConfirmDeactivateOpen] = useState(false);

  const { run: runUpdate, state: updateState } = useAsyncAction(() =>
    updateResalePlan(tenantId, plan.id, {
      name,
      ...(description.trim() ? { description: description.trim() } : { clearDescription: true }),
    }),
  );
  const { run: runDeactivate, state: deactivateState } = useAsyncAction(() =>
    deactivateResalePlan(tenantId, plan.id),
  );

  const isEnabled = plan.status === RESALE_PLAN_STATUS_ENABLED;

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--space-2)", flexWrap: "wrap" }}>
        <div>
          <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: "var(--font-size-md)" }}>{plan.name}</h3>
            <Badge tone="neutral">{plan.key}</Badge>
            <Badge tone={isEnabled ? "success" : "neutral"}>{plan.status}</Badge>
          </div>
          <p style={{ margin: "var(--space-1) 0 0", fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
            {priceLabel(plan)}
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-1)" }}>
          <Button variant="secondary" size="sm" onClick={() => setEditing((v) => !v)}>
            {editing ? "Cancel" : "Edit"}
          </Button>
          {isEnabled ? (
            <Button variant="danger" size="sm" onClick={() => setConfirmDeactivateOpen(true)}>
              Deactivate
            </Button>
          ) : null}
        </div>
      </div>

      {plan.description && !editing ? (
        <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-sm)" }}>{plan.description}</p>
      ) : null}

      {editing ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (!name.trim()) return;
            const saved = await runUpdate();
            if (saved) {
              setEditing(false);
              onChanged();
            }
          }}
          style={{ marginTop: "var(--space-3)", display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
        >
          <Input label="Name" required value={name} onChange={(event) => setName(event.target.value)} maxLength={200} />
          <Input
            label="Description (optional)"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={1000}
          />
          <div>
            <Button type="submit" size="sm" disabled={updateState.status === "pending" || !name.trim()}>
              {updateState.status === "pending" ? "Saving…" : "Save"}
            </Button>
          </div>
          {updateState.status === "error" ? (
            <InlineNotice tone="danger">{updateState.error.message}</InlineNotice>
          ) : null}
        </form>
      ) : null}

      {deactivateState.status === "error" ? (
        <InlineNotice tone="danger">{deactivateState.error.message}</InlineNotice>
      ) : null}
      <ConfirmDialog
        open={confirmDeactivateOpen}
        title="Deactivate this resale plan?"
        description="It will no longer be offered to new subscribers. Tenants already subscribed against it are unaffected."
        confirmLabel="Deactivate"
        danger
        pending={deactivateState.status === "pending"}
        onConfirm={async () => {
          await runDeactivate();
          setConfirmDeactivateOpen(false);
          onChanged();
        }}
        onCancel={() => setConfirmDeactivateOpen(false)}
      />
    </Card>
  );
}

function CreateResalePlanForm({ tenantId, onCreated }: { tenantId: string; onCreated: () => void }) {
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [priceAmount, setPriceAmount] = useState("");
  const [priceCurrency, setPriceCurrency] = useState("USD");
  const [billingInterval, setBillingInterval] = useState<string>(BILLING_INTERVALS[0]);

  const parsedPrice = Number(priceAmount);
  const canSubmit =
    key.trim() !== "" &&
    name.trim() !== "" &&
    priceAmount.trim() !== "" &&
    Number.isInteger(parsedPrice) &&
    parsedPrice >= 0 &&
    priceCurrency.trim() !== "";

  const { state, run } = useAsyncAction(() =>
    createResalePlan(tenantId, {
      key: key.trim(),
      name: name.trim(),
      description: description.trim() || null,
      price_amount: parsedPrice,
      price_currency: priceCurrency.trim().toUpperCase(),
      billing_interval: billingInterval,
    }),
  );

  return (
    <Card>
      <h3 style={{ marginTop: 0, fontSize: "var(--font-size-md)" }}>Create a resale plan</h3>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!canSubmit) return;
          const created = await run();
          if (created) {
            setKey("");
            setName("");
            setDescription("");
            setPriceAmount("");
            onCreated();
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
      >
        <FormRow>
          <FormRowGrow>
            <Input label="Key" required value={key} onChange={(event) => setKey(event.target.value)} maxLength={100} placeholder="starter" />
          </FormRowGrow>
          <FormRowGrow>
            <Input label="Name" required value={name} onChange={(event) => setName(event.target.value)} maxLength={200} placeholder="Starter" />
          </FormRowGrow>
        </FormRow>
        <Input
          label="Description (optional)"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          maxLength={1000}
        />
        <FormRow>
          <div style={{ width: 140 }}>
            <Input
              label="Price"
              required
              type="number"
              min={0}
              step={1}
              value={priceAmount}
              onChange={(event) => setPriceAmount(event.target.value)}
            />
          </div>
          <div style={{ width: 100 }}>
            <Input
              label="Currency"
              required
              value={priceCurrency}
              onChange={(event) => setPriceCurrency(event.target.value)}
              maxLength={3}
              placeholder="USD"
            />
          </div>
          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Interval</span>
            <select value={billingInterval} onChange={(event) => setBillingInterval(event.target.value)}>
              {BILLING_INTERVALS.map((interval) => (
                <option key={interval} value={interval}>
                  {interval}
                </option>
              ))}
            </select>
          </label>
        </FormRow>
        <div>
          <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
            {state.status === "pending" ? "Creating…" : "Create resale plan"}
          </Button>
        </div>
        {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      </form>
    </Card>
  );
}

export function ResalePlansPanel({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => listResalePlans(tenantId), [tenantId]);

  if (query.status === "loading") return <LoadingState label="Loading resale plans…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {query.data.length === 0 ? (
        <EmptyState
          title="No resale plans yet"
          description="Create a resale plan to offer a commercial catalog to the tenants below you."
        />
      ) : (
        query.data.map((plan) => (
          <ResalePlanRow key={plan.id} tenantId={tenantId} plan={plan} onChanged={query.refetch} />
        ))
      )}
      <CreateResalePlanForm tenantId={tenantId} onCreated={query.refetch} />
    </div>
  );
}
