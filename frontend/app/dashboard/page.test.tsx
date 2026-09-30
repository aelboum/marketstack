import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DashboardEntryPage from "./page";
import { ApiError } from "@/lib/api/errors";

const pushMock = vi.fn();
const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
}));

const { statusMock } = vi.hoisted(() => ({ statusMock: vi.fn() }));
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ status: statusMock() }),
}));

const { getLastTenantIdMock } = vi.hoisted(() => ({ getLastTenantIdMock: vi.fn() }));
vi.mock("@/lib/tenant/last-tenant", () => ({
  getLastTenantId: getLastTenantIdMock,
}));

const { createAgencyMock } = vi.hoisted(() => ({ createAgencyMock: vi.fn() }));
vi.mock("@/lib/api/agency", () => ({
  createAgency: createAgencyMock,
}));

vi.mock("@/lib/auth/api", () => ({
  loginUrl: () => "/auth/login",
}));

const locationAssignMock = vi.fn();

describe("DashboardEntryPage (UI-11 tenant-less entry point)", () => {
  beforeEach(() => {
    pushMock.mockClear();
    replaceMock.mockClear();
    getLastTenantIdMock.mockReturnValue(null);
    createAgencyMock.mockReset();
    locationAssignMock.mockClear();
    // jsdom's real `window.location.assign` throws "Not implemented:
    // navigation" -- replacing the whole object (rather than spying on
    // one property, which jsdom's `location` does not allow redefining)
    // is what other pages in this product also work around when they
    // exercise the same `window.location.assign(loginUrl())` call.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, assign: locationAssignMock },
    });
  });

  it("shows a loading state while session status is loading", () => {
    statusMock.mockReturnValue("loading");
    render(<DashboardEntryPage />);
    expect(screen.getAllByText("Loading your workspace…").length).toBeGreaterThan(0);
    expect(screen.queryByText("No workspace selected")).not.toBeInTheDocument();
  });

  it("sends an unauthenticated visitor to sign in, not the workspace card", () => {
    statusMock.mockReturnValue("unauthenticated");
    render(<DashboardEntryPage />);
    expect(screen.getAllByText("Redirecting to sign in…").length).toBeGreaterThan(0);
    expect(locationAssignMock).toHaveBeenCalledWith("/auth/login");
    expect(screen.queryByText("No workspace selected")).not.toBeInTheDocument();
  });

  it("resumes the last tenant automatically, without showing the workspace card", () => {
    statusMock.mockReturnValue("authenticated");
    getLastTenantIdMock.mockReturnValue("tenant-9");
    render(<DashboardEntryPage />);
    expect(replaceMock).toHaveBeenCalledWith("/t/tenant-9/dashboard");
    expect(screen.queryByText("No workspace selected")).not.toBeInTheDocument();
  });

  it("shows the manual-tenant-id and create-agency card when there is no last tenant", () => {
    statusMock.mockReturnValue("authenticated");
    render(<DashboardEntryPage />);
    expect(screen.getByText("No workspace selected")).toBeInTheDocument();
    expect(screen.getByLabelText("Tenant ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Agency name")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("navigates to a manually entered tenant id", async () => {
    statusMock.mockReturnValue("authenticated");
    const user = userEvent.setup();
    render(<DashboardEntryPage />);

    await user.type(screen.getByLabelText("Tenant ID"), "tenant-manual");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(pushMock).toHaveBeenCalledWith("/t/tenant-manual/dashboard");
  });

  it("disables the manual-continue button until an id is entered", () => {
    statusMock.mockReturnValue("authenticated");
    render(<DashboardEntryPage />);
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("disables create-agency submit until a name is entered", () => {
    statusMock.mockReturnValue("authenticated");
    render(<DashboardEntryPage />);
    expect(screen.getByRole("button", { name: "Create agency" })).toBeDisabled();
  });

  it("creates a new agency and redirects into its own tenant dashboard on success", async () => {
    statusMock.mockReturnValue("authenticated");
    createAgencyMock.mockResolvedValue({ tenant_id: "new-tenant-1", name: "Acme Marketing" });
    const user = userEvent.setup();
    render(<DashboardEntryPage />);

    await user.type(screen.getByLabelText("Agency name"), "Acme Marketing");
    await user.click(screen.getByRole("button", { name: "Create agency" }));

    await waitFor(() => expect(createAgencyMock).toHaveBeenCalledWith("Acme Marketing"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/t/new-tenant-1/dashboard"));
  });

  it("shows the backend's error and does not navigate when agency creation fails", async () => {
    statusMock.mockReturnValue("authenticated");
    createAgencyMock.mockRejectedValue(new ApiError("validation", "That name is already in use."));
    const user = userEvent.setup();
    render(<DashboardEntryPage />);

    await user.type(screen.getByLabelText("Agency name"), "Acme Marketing");
    await user.click(screen.getByRole("button", { name: "Create agency" }));

    await waitFor(() =>
      expect(screen.getByText("That name is already in use.")).toBeInTheDocument(),
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("disables the create-agency button while the request is in flight (duplicate-submit protection)", async () => {
    statusMock.mockReturnValue("authenticated");
    let resolveCreate: (() => void) | undefined;
    createAgencyMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = () => resolve({ tenant_id: "new-tenant-1", name: "Acme Marketing" });
        }),
    );
    const user = userEvent.setup();
    render(<DashboardEntryPage />);

    await user.type(screen.getByLabelText("Agency name"), "Acme Marketing");
    await user.click(screen.getByRole("button", { name: "Create agency" }));

    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(createAgencyMock).toHaveBeenCalledOnce();

    resolveCreate?.();
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/t/new-tenant-1/dashboard"));
    expect(createAgencyMock).toHaveBeenCalledOnce();
  });
});
