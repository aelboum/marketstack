import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WebsitesPage from "./page";
import { TenantProvider } from "@/lib/tenant/tenant-context";

vi.mock("next/navigation", () => ({ usePathname: () => "/t/t1/websites" }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listWebsitesMock, createWebsiteMock } = vi.hoisted(() => ({
  listWebsitesMock: vi.fn(),
  createWebsiteMock: vi.fn(),
}));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, listWebsites: listWebsitesMock, createWebsite: createWebsiteMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function renderPage() {
  return render(
    <TenantProvider tenantId="t1">
      <WebsitesPage />
    </TenantProvider>,
  );
}

describe("WebsitesPage", () => {
  it("scopes the website list to the tenant from the route context", async () => {
    listWebsitesMock.mockResolvedValue({ results: [], hasMore: false });
    renderPage();
    await waitFor(() => expect(listWebsitesMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }));
  });

  it("creating a website closes the dialog and reloads the list", async () => {
    listWebsitesMock.mockResolvedValue({ results: [], hasMore: false });
    createWebsiteMock.mockResolvedValue({ id: "w1", slug: "my-site" });
    const user = userEvent.setup();

    renderPage();
    await waitFor(() => expect(screen.getByText("No websites yet")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "New website" }));
    const dialog = screen.getByRole("dialog", { name: "New website" });

    await user.type(within(dialog).getByLabelText("Slug"), "my-site");
    await user.type(within(dialog).getByLabelText("Name"), "My Site");
    await user.click(within(dialog).getByRole("button", { name: "Create website" }));

    await waitFor(() => expect(createWebsiteMock).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listWebsitesMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
