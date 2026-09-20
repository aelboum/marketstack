import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ClientsList } from "./ClientsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listClientsMock } = vi.hoisted(() => ({ listClientsMock: vi.fn() }));
vi.mock("@/lib/api/agency", () => ({ listClients: listClientsMock }));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ClientsList", () => {
  it("shows a loading state, then the real client list from the API", async () => {
    listClientsMock.mockResolvedValue([
      { tenant_id: "c1", name: "Acme Dental" },
      { tenant_id: "c2", name: "Acme Legal" },
    ]);

    render(<ClientsList agencyTenantId="agency-1" />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Acme Dental")).toBeInTheDocument());
    expect(screen.getByText("Acme Legal")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "View →" });
    expect(links[0]).toHaveAttribute("href", "/t/agency-1/clients/c1");
    expect(links[1]).toHaveAttribute("href", "/t/agency-1/clients/c2");
  });

  it("shows an empty state when the API returns no clients", async () => {
    listClientsMock.mockResolvedValue([]);
    render(<ClientsList agencyTenantId="agency-1" />);

    await waitFor(() => expect(screen.getByText("No clients yet")).toBeInTheDocument());
  });

  it("shows a permission-denied state on a 404/403 (non-enumerating) response", async () => {
    listClientsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<ClientsList agencyTenantId="agency-1" />);

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("caps rows with `limit` and links to the full clients page", async () => {
    listClientsMock.mockResolvedValue([
      { tenant_id: "c1", name: "One" },
      { tenant_id: "c2", name: "Two" },
      { tenant_id: "c3", name: "Three" },
    ]);
    render(<ClientsList agencyTenantId="agency-1" limit={2} />);

    await waitFor(() => expect(screen.getByText("One")).toBeInTheDocument());
    expect(screen.getByText("Two")).toBeInTheDocument();
    expect(screen.queryByText("Three")).not.toBeInTheDocument();
    expect(screen.getByText("View all 3 clients →")).toBeInTheDocument();
  });
});
