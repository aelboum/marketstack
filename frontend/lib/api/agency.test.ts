import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  acceptInvitation,
  approveSupportAccess,
  createAgency,
  createClient,
  createDelegation,
  createDeny,
  denySupportAccess,
  inviteMember,
  listClients,
  requestSupportAccess,
  revokeDelegation,
  revokeDeny,
  revokeSupportAccess,
} from "./agency";

describe("agency API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("createAgency() -> POST /v1/agency/agencies", async () => {
    requestMock.mockResolvedValue({ tenant_id: "t1", name: "Acme" });
    await createAgency("Acme");
    expect(requestMock).toHaveBeenCalledWith("/v1/agency/agencies", {
      method: "POST",
      body: { name: "Acme" },
    });
  });

  it("createClient() -> POST /v1/agency/agencies/{agencyTenantId}/clients", async () => {
    requestMock.mockResolvedValue({});
    await createClient("agency-1", "Client A");
    expect(requestMock).toHaveBeenCalledWith("/v1/agency/agencies/agency-1/clients", {
      method: "POST",
      body: { name: "Client A" },
    });
  });

  it("listClients() -> GET /v1/agency/agencies/{agencyTenantId}/clients", async () => {
    requestMock.mockResolvedValue([]);
    await listClients("agency-1");
    expect(requestMock).toHaveBeenCalledWith("/v1/agency/agencies/agency-1/clients");
  });

  it("inviteMember() -> POST /v1/agency/tenants/{tenantId}/invitations", async () => {
    requestMock.mockResolvedValue({});
    await inviteMember("tenant-1", "a@example.com");
    expect(requestMock).toHaveBeenCalledWith("/v1/agency/tenants/tenant-1/invitations", {
      method: "POST",
      body: { invited_email: "a@example.com" },
    });
  });

  it("acceptInvitation() -> POST /v1/agency/tenants/{tenantId}/invitations/accept", async () => {
    requestMock.mockResolvedValue({});
    await acceptInvitation("tenant-1", "raw-token");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/agency/tenants/tenant-1/invitations/accept",
      { method: "POST", body: { raw_token: "raw-token" } },
    );
  });

  it("createDelegation() sends snake_case fields and defaults scope_mode to 'self'", async () => {
    requestMock.mockResolvedValue({});
    await createDelegation("tenant-1", {
      delegateUserId: "user-1",
      resource: "agency.client",
      action: "read",
    });
    expect(requestMock).toHaveBeenCalledWith("/v1/agency/tenants/tenant-1/delegations", {
      method: "POST",
      body: {
        delegate_user_id: "user-1",
        resource: "agency.client",
        action: "read",
        scope_mode: "self",
        expires_at: null,
        allow_redelegate: false,
      },
    });
  });

  it("revokeDelegation() -> DELETE /v1/agency/tenants/{tenantId}/delegations/{id}", async () => {
    requestMock.mockResolvedValue(undefined);
    await revokeDelegation("tenant-1", "delegation-1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/agency/tenants/tenant-1/delegations/delegation-1",
      { method: "DELETE" },
    );
  });

  it("createDeny() sends snake_case fields", async () => {
    requestMock.mockResolvedValue({});
    await createDeny("tenant-1", {
      principalUserId: "user-2",
      resource: "agency.client",
      action: "create",
      scopeMode: "subtree",
    });
    expect(requestMock).toHaveBeenCalledWith("/v1/agency/tenants/tenant-1/denies", {
      method: "POST",
      body: {
        principal_user_id: "user-2",
        resource: "agency.client",
        action: "create",
        scope_mode: "subtree",
      },
    });
  });

  it("revokeDeny() -> DELETE /v1/agency/tenants/{tenantId}/denies/{id}", async () => {
    requestMock.mockResolvedValue(undefined);
    await revokeDeny("tenant-1", "deny-1");
    expect(requestMock).toHaveBeenCalledWith("/v1/agency/tenants/tenant-1/denies/deny-1", {
      method: "DELETE",
    });
  });

  it("requestSupportAccess() -> POST .../support-access-requests", async () => {
    requestMock.mockResolvedValue({});
    await requestSupportAccess("tenant-1", {
      reason: "ticket #1",
      requestedExpiresAt: "2026-01-01T00:00:00.000Z",
    });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/agency/tenants/tenant-1/support-access-requests",
      {
        method: "POST",
        body: { reason: "ticket #1", requested_expires_at: "2026-01-01T00:00:00.000Z", scope_mode: "self" },
      },
    );
  });

  it("approveSupportAccess()/denySupportAccess()/revokeSupportAccess() hit the right sub-paths", async () => {
    requestMock.mockResolvedValue({});
    await approveSupportAccess("tenant-1", "req-1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/agency/tenants/tenant-1/support-access-requests/req-1/approve",
      { method: "POST" },
    );

    await denySupportAccess("tenant-1", "req-1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/agency/tenants/tenant-1/support-access-requests/req-1/deny",
      { method: "POST" },
    );

    await revokeSupportAccess("tenant-1", "req-1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/agency/tenants/tenant-1/support-access-requests/req-1/revoke",
      { method: "POST" },
    );
  });
});
