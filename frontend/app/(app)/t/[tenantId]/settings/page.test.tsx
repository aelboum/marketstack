import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import SettingsPage from "./page";
import { TenantProvider } from "@/lib/tenant/tenant-context";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/tenant-from-route/settings" }));
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

function renderPage(tenantId = "tenant-from-route") {
  return render(
    <TenantProvider tenantId={tenantId}>
      <SettingsPage />
    </TenantProvider>,
  );
}

describe("SettingsPage", () => {
  it("scopes its API call to the tenant from the route context, not a stored value", async () => {
    listClientsMock.mockResolvedValue([]);
    renderPage();

    await waitFor(() => expect(listClientsMock).toHaveBeenCalledWith("tenant-from-route"));
    expect(screen.getByText("tenant-from-route")).toBeInTheDocument();
  });

  it("renders the settings shell with its navigation around the page content", async () => {
    listClientsMock.mockResolvedValue([]);
    renderPage();

    expect(screen.getByTestId("settings-shell")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Settings sections" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 2, name: "Workspace" })).toBeInTheDocument(),
    );
  });

  it("renders the permission-denied state inside the shell, keeping navigation usable", async () => {
    listClientsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
    // A failed section must not take the whole settings area down with it.
    expect(screen.getByRole("navigation", { name: "Settings sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Profile/ })).toBeInTheDocument();
  });
});
