import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThreadsList } from "./ThreadsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listThreadsMock, listContactsMock } = vi.hoisted(() => ({
  listThreadsMock: vi.fn(),
  listContactsMock: vi.fn(),
}));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return { ...actual, listThreads: listThreadsMock };
});
vi.mock("@/lib/api/crm", () => ({ listContacts: listContactsMock }));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ThreadsList", () => {
  it("shows loading, then real threads with resolved contact names", async () => {
    listThreadsMock.mockResolvedValue({
      results: [
        {
          id: "th1",
          tenant_id: "t1",
          contact_id: "c1",
          channel: "email",
          assigned_to_user_id: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
      hasMore: false,
    });
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Jane", last_name: "Doe" }],
      hasMore: false,
    });

    render(<ThreadsList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(screen.getByText("email")).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Jane Doe/ })).toHaveAttribute(
      "href",
      "/t/t1/conversations/th1",
    );
  });

  it("shows an empty state with no conversations", async () => {
    listThreadsMock.mockResolvedValue({ results: [], hasMore: false });
    listContactsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<ThreadsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No conversations yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listThreadsMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    listContactsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<ThreadsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("paginates via Previous/Next using limit/offset, never a fabricated total", async () => {
    listContactsMock.mockResolvedValue({ results: [], hasMore: false });
    listThreadsMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => ({
        id: `th${i}`,
        tenant_id: "t1",
        contact_id: null,
        channel: "chat",
        assigned_to_user_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<ThreadsList tenantId="t1" />);
    await waitFor(() => expect(listThreadsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }));

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(listThreadsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 25 }));
  });
});
