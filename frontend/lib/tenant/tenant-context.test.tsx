import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TenantProvider, useTenant, useOptionalTenant } from "./tenant-context";
import { getLastTenantId } from "./last-tenant";

function Probe() {
  const { tenantId } = useTenant();
  return <span data-testid="tenant">{tenantId}</span>;
}

function OptionalProbe() {
  const tenant = useOptionalTenant();
  return <span data-testid="optional">{tenant ? tenant.tenantId : "none"}</span>;
}

describe("TenantProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("exposes the tenant id given by the route", () => {
    render(
      <TenantProvider tenantId="tenant-42">
        <Probe />
      </TenantProvider>,
    );
    expect(screen.getByTestId("tenant")).toHaveTextContent("tenant-42");
  });

  it("remembers the tenant id as the last-used tenant (UX convenience only)", () => {
    render(
      <TenantProvider tenantId="tenant-42">
        <Probe />
      </TenantProvider>,
    );
    expect(getLastTenantId()).toBe("tenant-42");
  });

  it("useOptionalTenant() returns null outside a TenantProvider instead of throwing", () => {
    render(<OptionalProbe />);
    expect(screen.getByTestId("optional")).toHaveTextContent("none");
  });

  it("useTenant() throws outside a TenantProvider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow();
    spy.mockRestore();
  });
});
