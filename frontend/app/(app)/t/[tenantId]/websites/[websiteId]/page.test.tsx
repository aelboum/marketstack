import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WebsiteDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", websiteId: "w1" }),
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { getWebsiteMock, listPagesMock, createPageMock, deleteWebsiteMock } = vi.hoisted(() => ({
  getWebsiteMock: vi.fn(),
  listPagesMock: vi.fn(),
  createPageMock: vi.fn(),
  deleteWebsiteMock: vi.fn(),
}));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return {
    ...actual,
    getWebsite: getWebsiteMock,
    listPages: listPagesMock,
    createPage: createPageMock,
    deleteWebsite: deleteWebsiteMock,
  };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const WEBSITE = {
  id: "w1",
  tenant_id: "tenant-1",
  slug: "my-site",
  name: "My Site",
  custom_domain: null,
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("WebsiteDetailPage", () => {
  it("renders the real website once fetched by id", async () => {
    getWebsiteMock.mockResolvedValue(WEBSITE);
    listPagesMock.mockResolvedValue({ results: [], hasMore: false });

    render(<WebsiteDetailPage />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "My Site" })).toBeInTheDocument(),
    );
    expect(getWebsiteMock).toHaveBeenCalledWith("tenant-1", "w1");
    await waitFor(() =>
      expect(listPagesMock).toHaveBeenCalledWith("tenant-1", "w1", { limit: 25, offset: 0 }),
    );
  });

  it("creating a page closes the dialog and reloads the pages list", async () => {
    getWebsiteMock.mockResolvedValue(WEBSITE);
    listPagesMock.mockResolvedValue({ results: [], hasMore: false });
    createPageMock.mockResolvedValue({ id: "p1", title: "Home" });
    const user = userEvent.setup();

    render(<WebsiteDetailPage />);
    await waitFor(() => expect(screen.getByText("No pages yet")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "New page" }));
    const dialog = screen.getByRole("dialog", { name: "New page" });

    await user.type(within(dialog).getByLabelText("Slug"), "home");
    await user.type(within(dialog).getByLabelText("Title"), "Home");
    await user.click(within(dialog).getByRole("button", { name: "Create page" }));

    await waitFor(() => expect(createPageMock).toHaveBeenCalledWith("tenant-1", "w1", { slug: "home", title: "Home" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listPagesMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("deleting the website navigates back to the websites list", async () => {
    getWebsiteMock.mockResolvedValue(WEBSITE);
    listPagesMock.mockResolvedValue({ results: [], hasMore: false });
    deleteWebsiteMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<WebsiteDetailPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete website" }));

    await waitFor(() => expect(deleteWebsiteMock).toHaveBeenCalledWith("tenant-1", "w1"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/t/tenant-1/websites"));
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    getWebsiteMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<WebsiteDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
