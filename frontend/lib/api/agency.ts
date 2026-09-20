// Typed API functions for the Phase 3 Agency/Client backend
// (`product/agency/routes.py`, mounted at `/v1/agency`), built on the
// UI-1 `request()` foundation (lib/api/client.ts) -- UI-2 adds no second
// HTTP client. Every shape below is taken directly from that router's
// own request/response models, not guessed from the OpenAPI schema
// (several of its routes return a loosely-typed `dict[str, object]`,
// which is why the exact field sets here matter -- verified by reading
// `product/agency/routes.py` itself).
//
// Real, discovered gaps this file's shape reflects rather than works
// around (see UI-2's final report for the full list):
//   - there is no GET for a single agency or a single client -- only
//     `listClients()` (`GET .../clients`) exists; a "client detail" view
//     must find its subject inside that list, not fetch it directly;
//   - delegations, denies, and support-access requests can be created,
//     revoked/approved/denied -- but never *listed*. There is no way to
//     show "current delegations on this tenant." Every panel built on
//     these functions is create/act-by-id only, not a managed table.

import { request } from "@/lib/api/client";

export type Agency = {
  tenant_id: string;
  name: string;
};

/** `GET /agencies/{agencyTenantId}/clients` list-item shape -- note: no
 * `agency_tenant_id` field (routes.py's `list_agency_clients` omits it;
 * only the create response includes it). */
export type ClientSummary = {
  tenant_id: string;
  name: string;
};

export type CreatedClient = ClientSummary & {
  agency_tenant_id: string;
};

export type InvitationSent = {
  invitation_id: string;
  /** The bearer credential itself -- shown to the inviter exactly once
   * (this response is the only place it ever appears; there is no
   * "resend"/"look up again" endpoint). Never log this value. */
  raw_token: string;
};

export type InvitationAccepted = {
  tenant_id: string;
  membership_id: string;
};

export type DelegationCreated = {
  delegation_id: string;
};

export type DenyCreated = {
  deny_id: string;
};

export type SupportAccessRequested = {
  request_id: string;
};

export type SupportAccessApproved = {
  request_id: string;
  approved_at: string;
};

export type SupportAccessDenied = {
  request_id: string;
  denied_at: string;
};

export type SupportAccessRevoked = {
  request_id: string;
  revoked_at: string;
};

/** `core.rbac.scope.RoleScope` -- exact wire values (StrEnum), not a
 * frontend invention. */
export type RoleScope = "self" | "subtree";

/**
 * `(resource, action)` pairs known, from reading
 * `product/agency/roles.py::_AGENCY_OWNER_CORE_PERMISSIONS` and
 * `AGENCY_CLIENT_RESOURCE`, to already be registered `core.rbac`
 * permissions as of this phase -- real, sourced identifiers, not
 * invented ones. Delegation/deny creation still accepts free-text
 * resource/action (this list is offered as a convenience, not treated
 * as exhaustive): other modules (CRM, Marketing, ...) register their own
 * permissions once their own phase ships, and this list has no way to
 * discover those -- there is no "list registered permissions" endpoint.
 */
export const KNOWN_DELEGATABLE_PERMISSIONS: ReadonlyArray<{
  resource: string;
  action: string;
  label: string;
}> = [
  { resource: "agency.client", action: "create", label: "Create clients" },
  { resource: "agency.client", action: "read", label: "View clients" },
  { resource: "invitation", action: "create", label: "Invite members" },
  { resource: "invitation", action: "revoke", label: "Revoke invitations" },
  { resource: "membership_role", action: "create", label: "Assign roles" },
  { resource: "delegation_grant", action: "create", label: "Create delegations" },
  { resource: "delegation_grant", action: "revoke", label: "Revoke delegations" },
  { resource: "deny_grant", action: "create", label: "Create denies" },
  { resource: "deny_grant", action: "revoke", label: "Revoke denies" },
  { resource: "support_access_request", action: "approve", label: "Approve support access" },
  { resource: "support_access_request", action: "deny", label: "Deny support access" },
  { resource: "support_access_request", action: "revoke", label: "Revoke support access" },
];

export function createAgency(name: string): Promise<Agency> {
  return request<Agency>("/v1/agency/agencies", { method: "POST", body: { name } });
}

export function createClient(agencyTenantId: string, name: string): Promise<CreatedClient> {
  return request<CreatedClient>(`/v1/agency/agencies/${agencyTenantId}/clients`, {
    method: "POST",
    body: { name },
  });
}

export function listClients(agencyTenantId: string): Promise<ClientSummary[]> {
  return request<ClientSummary[]>(`/v1/agency/agencies/${agencyTenantId}/clients`);
}

export function inviteMember(tenantId: string, invitedEmail: string): Promise<InvitationSent> {
  return request<InvitationSent>(`/v1/agency/tenants/${tenantId}/invitations`, {
    method: "POST",
    body: { invited_email: invitedEmail },
  });
}

export function acceptInvitation(
  tenantId: string,
  rawToken: string,
): Promise<InvitationAccepted> {
  return request<InvitationAccepted>(`/v1/agency/tenants/${tenantId}/invitations/accept`, {
    method: "POST",
    body: { raw_token: rawToken },
  });
}

export type CreateDelegationInput = {
  delegateUserId: string;
  resource: string;
  action: string;
  scopeMode?: RoleScope;
  expiresAt?: string | null;
  allowRedelegate?: boolean;
};

export function createDelegation(
  tenantId: string,
  input: CreateDelegationInput,
): Promise<DelegationCreated> {
  return request<DelegationCreated>(`/v1/agency/tenants/${tenantId}/delegations`, {
    method: "POST",
    body: {
      delegate_user_id: input.delegateUserId,
      resource: input.resource,
      action: input.action,
      scope_mode: input.scopeMode ?? "self",
      expires_at: input.expiresAt ?? null,
      allow_redelegate: input.allowRedelegate ?? false,
    },
  });
}

export function revokeDelegation(tenantId: string, delegationId: string): Promise<void> {
  return request<void>(`/v1/agency/tenants/${tenantId}/delegations/${delegationId}`, {
    method: "DELETE",
  });
}

export type CreateDenyInput = {
  principalUserId: string;
  resource: string;
  action: string;
  scopeMode?: RoleScope;
};

export function createDeny(tenantId: string, input: CreateDenyInput): Promise<DenyCreated> {
  return request<DenyCreated>(`/v1/agency/tenants/${tenantId}/denies`, {
    method: "POST",
    body: {
      principal_user_id: input.principalUserId,
      resource: input.resource,
      action: input.action,
      scope_mode: input.scopeMode ?? "self",
    },
  });
}

export function revokeDeny(tenantId: string, denyId: string): Promise<void> {
  return request<void>(`/v1/agency/tenants/${tenantId}/denies/${denyId}`, { method: "DELETE" });
}

export type RequestSupportAccessInput = {
  reason: string;
  requestedExpiresAt: string;
  scopeMode?: RoleScope;
};

export function requestSupportAccess(
  tenantId: string,
  input: RequestSupportAccessInput,
): Promise<SupportAccessRequested> {
  return request<SupportAccessRequested>(`/v1/agency/tenants/${tenantId}/support-access-requests`, {
    method: "POST",
    body: {
      reason: input.reason,
      requested_expires_at: input.requestedExpiresAt,
      scope_mode: input.scopeMode ?? "self",
    },
  });
}

export function approveSupportAccess(
  tenantId: string,
  requestId: string,
): Promise<SupportAccessApproved> {
  return request<SupportAccessApproved>(
    `/v1/agency/tenants/${tenantId}/support-access-requests/${requestId}/approve`,
    { method: "POST" },
  );
}

export function denySupportAccess(
  tenantId: string,
  requestId: string,
): Promise<SupportAccessDenied> {
  return request<SupportAccessDenied>(
    `/v1/agency/tenants/${tenantId}/support-access-requests/${requestId}/deny`,
    { method: "POST" },
  );
}

export function revokeSupportAccess(
  tenantId: string,
  requestId: string,
): Promise<SupportAccessRevoked> {
  return request<SupportAccessRevoked>(
    `/v1/agency/tenants/${tenantId}/support-access-requests/${requestId}/revoke`,
    { method: "POST" },
  );
}
