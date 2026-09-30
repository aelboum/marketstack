// Typed API functions for the Phase 13 Billing/Resale backend
// (`product/billing/routes.py`, mounted at `/v1/billing`), built on the
// UI-1 `request()` foundation (lib/api/client.ts) -- mirrors
// lib/api/agency.ts/lib/api/crm.ts's own pattern; UI-14 adds no second
// HTTP client. Every shape below is read directly off that router's own
// `_resale_plan_dict()`/`_subscription_dict()` response builders and
// request models (product/billing/routes.py), not guessed from a schema.
//
// Non-enumeration: 403 and a tenant-scoped 404 both collapse to the same
// `lib/api/client.ts` `ApiError` "forbidden" kind -- nothing billing-
// specific needed here (product/billing/routes.py's own module docstring:
// "Non-enumeration" section).
//
// `price_amount` is a plain non-negative integer with no documented
// minor-unit (cents) convention anywhere in `product/billing/models.py` --
// this client renders it exactly as returned rather than guessing a
// decimal scale.
//
// `idempotency_key`: `POST .../subscriptions` requires a non-empty one
// (`CreateSubscriptionRequest.idempotency_key`, min_length=1) -- this is
// the one Billing write with no natural client-supplied identifier to
// reuse, so `createSubscription()` mints one fresh per call via
// `crypto.randomUUID()`, exactly once per submit (the existing
// `useAsyncAction` duplicate-submit guard is what keeps a given submit to
// exactly one call in the first place).

import { request } from "@/lib/api/client";

/** The global, product-agnostic plan catalog (`GET /v1/billing/plans`).
 * Not tenant-owned -- any authenticated actor may read it. */
export type Plan = {
  key: string;
  name: string;
  entitlements: Record<string, unknown>;
};

export const RESALE_PLAN_STATUS_ENABLED = "enabled";
export const RESALE_PLAN_STATUS_DISABLED = "disabled";

/** A reseller tenant's own commercial catalog entry
 * (`product/billing/models.py::ResalePlan`). `status` is an open string
 * (today: "enabled" | "disabled") -- rendered, never matched exhaustively. */
export type ResalePlan = {
  id: string;
  tenant_id: string;
  key: string;
  name: string;
  description: string | null;
  price_amount: number;
  price_currency: string;
  billing_interval: string;
  entitlements: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
};

/** One tenant's subscription state against a `core.billing.Plan`.
 * `status` is an open string (today: "active" | "canceled") -- rendered,
 * never matched exhaustively (core/billing/models.py::Subscription's own
 * docstring: "new statuses are added by extending the service, never by
 * a schema migration"). */
export type Subscription = {
  id: string;
  tenant_id: string;
  plan_id: string;
  plan_key: string;
  resale_plan_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};

/** `GET .../entitlements` -- an arbitrary, plan-defined key/value map.
 * Informational display only; the backend remains the sole enforcement
 * point for every entitlement (this phase's own scope). */
export type Entitlements = Record<string, unknown>;

// --- Platform plan catalog (read-only, not tenant-scoped) -------------------

export function listPlans(): Promise<Plan[]> {
  return request<Plan[]>("/v1/billing/plans");
}

// --- Resale plans (a reseller tenant's own catalog) -------------------------

export function listResalePlans(tenantId: string): Promise<ResalePlan[]> {
  return request<ResalePlan[]>(`/v1/billing/tenants/${tenantId}/resale-plans`);
}

/** Resale plans this tenant may subscribe to (offered by an ancestor
 * reseller) -- a distinct list from `listResalePlans()`, which is this
 * tenant's own authored catalog as a reseller. */
export function listAvailableResalePlans(tenantId: string): Promise<ResalePlan[]> {
  return request<ResalePlan[]>(`/v1/billing/tenants/${tenantId}/available-resale-plans`);
}

export function getResalePlan(tenantId: string, resalePlanId: string): Promise<ResalePlan> {
  return request<ResalePlan>(`/v1/billing/tenants/${tenantId}/resale-plans/${resalePlanId}`);
}

export function createResalePlan(
  tenantId: string,
  input: {
    key: string;
    name: string;
    description?: string | null;
    price_amount: number;
    price_currency: string;
    billing_interval: string;
  },
): Promise<ResalePlan> {
  return request<ResalePlan>(`/v1/billing/tenants/${tenantId}/resale-plans`, {
    method: "POST",
    body: input,
  });
}

/** `description: undefined` leaves it unchanged; `clearDescription: true`
 * explicitly nulls it -- mirrors the route's own
 * "omitted vs. explicit null" disambiguation
 * (product/billing/routes.py::update_resale_plan_route). */
export function updateResalePlan(
  tenantId: string,
  resalePlanId: string,
  input: { name?: string; description?: string; clearDescription?: boolean },
): Promise<ResalePlan> {
  return request<ResalePlan>(`/v1/billing/tenants/${tenantId}/resale-plans/${resalePlanId}`, {
    method: "PATCH",
    body: {
      name: input.name,
      description: input.description,
      clear_description: input.clearDescription ?? false,
    },
  });
}

export function deactivateResalePlan(
  tenantId: string,
  resalePlanId: string,
): Promise<ResalePlan> {
  return request<ResalePlan>(
    `/v1/billing/tenants/${tenantId}/resale-plans/${resalePlanId}/deactivate`,
    { method: "POST" },
  );
}

// --- Subscriptions -----------------------------------------------------------

export function listSubscriptions(tenantId: string): Promise<Subscription[]> {
  return request<Subscription[]>(`/v1/billing/tenants/${tenantId}/subscriptions`);
}

export function getSubscription(tenantId: string, subscriptionId: string): Promise<Subscription> {
  return request<Subscription>(`/v1/billing/tenants/${tenantId}/subscriptions/${subscriptionId}`);
}

/** Exactly one of `platformPlanKey`/`resalePlanId` must be supplied --
 * mirrors the route's own exactly-one-of validation
 * (product/billing/routes.py::create_subscription_route). */
export function createSubscription(
  tenantId: string,
  input: { platformPlanKey?: string; resalePlanId?: string },
): Promise<Subscription> {
  return request<Subscription>(`/v1/billing/tenants/${tenantId}/subscriptions`, {
    method: "POST",
    body: {
      idempotency_key: crypto.randomUUID(),
      platform_plan_key: input.platformPlanKey ?? null,
      resale_plan_id: input.resalePlanId ?? null,
    },
  });
}

export function changeSubscriptionPlan(
  tenantId: string,
  subscriptionId: string,
  input: { platformPlanKey?: string; resalePlanId?: string },
): Promise<Subscription> {
  return request<Subscription>(
    `/v1/billing/tenants/${tenantId}/subscriptions/${subscriptionId}/change-plan`,
    {
      method: "POST",
      body: {
        platform_plan_key: input.platformPlanKey ?? null,
        resale_plan_id: input.resalePlanId ?? null,
      },
    },
  );
}

export function cancelSubscription(
  tenantId: string,
  subscriptionId: string,
): Promise<Subscription> {
  return request<Subscription>(
    `/v1/billing/tenants/${tenantId}/subscriptions/${subscriptionId}/cancel`,
    { method: "POST" },
  );
}

// --- Effective entitlements (informational) ----------------------------------

export function getEntitlements(tenantId: string): Promise<Entitlements> {
  return request<Entitlements>(`/v1/billing/tenants/${tenantId}/entitlements`);
}
