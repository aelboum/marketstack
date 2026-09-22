import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PagesList } from "./PagesList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listPagesMock } = vi.hoisted(() => ({ listPagesMock: vi.fn() }));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, listPages: listPagesMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function page(overrides: Record<string, unknown> = {}) {
  return {
    id: "p1",
    tenant_id: "t1",
    website_id: "w1",
    slug: "home",
    title: "Home",
    status: "draft",
    content_blocks: [],
    published_at: null,
    created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("PagesList", () => {
  it("shows loading, then real pages linked to their detail page", async () => {
    listPagesMock.mockResolvedValue({ results: [page()], hasMore: false });
    render(<PagesList tenantId="t1" websiteId="w1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Home")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /Home/ })).toHaveAttribute(
      "href",
      "/t/t1/websites/w1/pages/p1",
    );
    expect(screen.getByText("draft")).toBeInTheDocument();
  });

  it("shows published timestamp when set", async () => {
    listPagesMock.mockResolvedValue({
      results: [page({ status: "published", published_at: "2026-02-01T00:00:00Z" })],
      hasMore: false,
    });
    render(<PagesList tenantId="t1" websiteId="w1" />);
    await waitFor(() => expect(screen.getByText("published")).toBeInTheDocument());
  });

  it("shows an empty state with no pages", async () => {
    listPagesMock.mockResolvedValue({ results: [], hasMore: false });
    render(<PagesList tenantId="t1" websiteId="w1" />);
    await waitFor(() => expect(screen.getByText("No pages yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listPagesMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<PagesList tenantId="t1" websiteId="w1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("paginates via Previous/Next using limit/offset", async () => {
    listPagesMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => page({ id: `p${i}`, title: `Page ${i}` })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<PagesList tenantId="t1" websiteId="w1" />);
    await waitFor(() =>
      expect(listPagesMock).toHaveBeenCalledWith("t1", "w1", { limit: 25, offset: 0 }),
    );

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(listPagesMock).toHaveBeenCalledWith("t1", "w1", { limit: 25, offset: 25 }),
    );
  });
});
