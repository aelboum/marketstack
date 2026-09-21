import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { GeneralSettingsPanel } from "./GeneralSettingsPanel";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/settings" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listClientsMock } = vi.hoisted(() => ({ listClientsMock: vi.fn() }));
vi.mock("@/lib/api/agency", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/agency")>();
  return { ...actual, listClients: listClientsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("GeneralSettingsPanel", () => {
  it("shows the tenant from the route and offers no rename control", async () => {
    listClientsMock.mockResolvedValue([]);
    render(<GeneralSettingsPanel tenantId="tenant-1" />);

    expect(screen.getByText("tenant-1")).toBeInTheDocument();
    // No name field and no rename button: the API has no tenant read or
    // update route, so offering one would be fake persistence.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /rename|save/i })).not.toBeInTheDocument();
    expect(screen.getByText(/cannot be read back or changed here/)).toBeInTheDocument();
  });

  it("scopes the clients call to the tenant in the route", async () => {
    listClientsMock.mockResolvedValue([]);
    render(<GeneralSettingsPanel tenantId="tenant-1" />);
    await waitFor(() => expect(listClientsMock).toHaveBeenCalledWith("tenant-1"));
  });

  it("shows a loading state, then the real client workspaces", async () => {
    listClientsMock.mockResolvedValue([
      { tenant_id: "c2", name: "Zeta Ltd" },
      { tenant_id: "c1", name: "Acme Inc" },
    ]);
    render(<GeneralSettingsPanel tenantId="tenant-1" />);

    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Acme Inc")).toBeInTheDocument());
    expect(screen.getByText(/Managing 2 client workspaces/)).toBeInTheDocument();
    // Backend returns an unordered set; the view sorts for stability.
    const links = screen.getAllByRole("link", { name: /Acme Inc|Zeta Ltd/ });
    expect(links[0]).toHaveTextContent("Acme Inc");
    expect(links[0]).toHaveAttribute("href", "/t/tenant-1/clients/c1");
  });

  it("shows an empty state when this workspace manages none", async () => {
    listClientsMock.mockResolvedValue([]);
    render(<GeneralSettingsPanel tenantId="tenant-1" />);
    await waitFor(() => expect(screen.getByText("No client workspaces")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    // What a `member` gets: every agency route is owner-only and answers
    // with the same 404 whether the caller lacks access or the workspace
    // simply is not an agency.
    listClientsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<GeneralSettingsPanel tenantId="tenant-1" />);

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("shows the session-expired state on 401", async () => {
    listClientsMock.mockRejectedValue(
      new ApiError("unauthorized", "session expired", { status: 401 }),
    );
    render(<GeneralSettingsPanel tenantId="tenant-1" />);

    await waitFor(() => expect(screen.getByText("Your session has expired")).toBeInTheDocument());
  });

  it("shows a retryable error state on a server failure", async () => {
    listClientsMock.mockRejectedValue(
      new ApiError("server", "Something went wrong talking to the backend.", { status: 500 }),
    );
    render(<GeneralSettingsPanel tenantId="tenant-1" />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument(),
    );
  });
});
