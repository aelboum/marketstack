import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WebsitePageDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", websiteId: "w1", pageId: "p1" }),
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { getPageMock, deletePageMock } = vi.hoisted(() => ({
  getPageMock: vi.fn(),
  deletePageMock: vi.fn(),
}));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, getPage: getPageMock, deletePage: deletePageMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const CONTENT_PAGE = {
  id: "p1",
  tenant_id: "tenant-1",
  website_id: "w1",
  slug: "home",
  title: "Home",
  status: "draft",
  content_blocks: [],
  published_at: null,
  created_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("WebsitePageDetailPage", () => {
  it("renders the real page once fetched by id, with a link back to its website", async () => {
    getPageMock.mockResolvedValue(CONTENT_PAGE);
    render(<WebsitePageDetailPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Home" })).toBeInTheDocument());
    expect(getPageMock).toHaveBeenCalledWith("tenant-1", "p1");
    expect(screen.getByRole("link", { name: /Back to website/ })).toHaveAttribute(
      "href",
      "/t/tenant-1/websites/w1",
    );
  });

  it("deleting the page navigates back to the website", async () => {
    getPageMock.mockResolvedValue(CONTENT_PAGE);
    deletePageMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<WebsitePageDetailPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete page" }));

    await waitFor(() => expect(deletePageMock).toHaveBeenCalledWith("tenant-1", "p1"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/t/tenant-1/websites/w1"));
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    getPageMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<WebsitePageDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
