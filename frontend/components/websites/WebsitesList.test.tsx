import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WebsitesList } from "./WebsitesList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listWebsitesMock } = vi.hoisted(() => ({ listWebsitesMock: vi.fn() }));
vi.mock("@/lib/api/websites", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/websites")>();
  return { ...actual, listWebsites: listWebsitesMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function website(overrides: Record<string, unknown> = {}) {
  return {
    id: "w1",
    tenant_id: "t1",
    slug: "my-site",
    name: "My Site",
    custom_domain: null,
    created_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

describe("WebsitesList", () => {
  it("shows loading, then real websites linked to their detail page", async () => {
    listWebsitesMock.mockResolvedValue({ results: [website()], hasMore: false });
    render(<WebsitesList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("My Site")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /My Site/ })).toHaveAttribute(
      "href",
      "/t/t1/websites/w1",
    );
  });

  it("shows None badge for a website with no custom domain, and the domain text when set", async () => {
    listWebsitesMock.mockResolvedValue({
      results: [website({ id: "w2", custom_domain: "example.com" })],
      hasMore: false,
    });
    render(<WebsitesList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("example.com")).toBeInTheDocument());
  });

  it("shows an empty state with no websites", async () => {
    listWebsitesMock.mockResolvedValue({ results: [], hasMore: false });
    render(<WebsitesList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No websites yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listWebsitesMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<WebsitesList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("paginates via Previous/Next using limit/offset, never a fabricated total", async () => {
    listWebsitesMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => website({ id: `w${i}`, name: `Site ${i}` })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<WebsitesList tenantId="t1" />);
    await waitFor(() => expect(listWebsitesMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }));

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(listWebsitesMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 25 }));
  });
});
