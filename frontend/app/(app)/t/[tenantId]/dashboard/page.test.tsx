import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import DashboardPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/tenant-1/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ status: "authenticated", user: { user_id: "user-1" }, markSessionExpired: vi.fn() }),
}));

vi.mock("@/lib/tenant/tenant-context", () => ({
  useTenant: () => ({ tenantId: "tenant-1" }),
}));

const { listClientsMock } = vi.hoisted(() => ({ listClientsMock: vi.fn() }));
vi.mock("@/lib/api/agency", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/agency")>();
  return { ...actual, listClients: listClientsMock };
});

describe("DashboardPage", () => {
  it("renders without fabricating metrics, shows the real client list, and links to every available module", async () => {
    listClientsMock.mockResolvedValue([{ tenant_id: "c1", name: "Acme Dental" }]);

    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/user-1/)).toBeInTheDocument();
    expect(screen.getByText(/tenant-1/)).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Acme Dental")).toBeInTheDocument());

    for (const label of ["CRM", "Conversations", "Marketing", "Appointments"]) {
      expect(screen.getByRole("link", { name: new RegExp(`Open ${label}`) })).toBeInTheDocument();
    }

    // No invented KPI/metric text -- UI-2 scope explicitly excludes this;
    // the one number that does appear (the client list) came from the
    // real, mocked API response above, not a hardcoded stat.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/MRR|revenue|conversion/i)).not.toBeInTheDocument();
  });

  it("opens the invite-teammate dialog from the dashboard header", async () => {
    listClientsMock.mockResolvedValue([]);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    render(<DashboardPage />);
    await waitFor(() => expect(screen.getByText("No clients yet")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Invite teammate" }));

    expect(screen.getByRole("dialog", { name: "Invite a teammate" })).toBeInTheDocument();
  });
});
