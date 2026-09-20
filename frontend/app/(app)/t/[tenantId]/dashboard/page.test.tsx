import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
  useSession: () => ({ status: "authenticated", user: { user_id: "user-1" } }),
}));

vi.mock("@/lib/tenant/tenant-context", () => ({
  useTenant: () => ({ tenantId: "tenant-1" }),
}));

describe("DashboardPage", () => {
  it("renders without fabricating metrics, and links to every available module", () => {
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByText(/user-1/)).toBeInTheDocument();
    expect(screen.getByText(/tenant-1/)).toBeInTheDocument();

    for (const label of ["CRM", "Conversations", "Marketing", "Appointments"]) {
      expect(screen.getByRole("link", { name: new RegExp(`Open ${label}`) })).toBeInTheDocument();
    }

    // No invented KPI/metric text -- UI-1 scope explicitly excludes this.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});
