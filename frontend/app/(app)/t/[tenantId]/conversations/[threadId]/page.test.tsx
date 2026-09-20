import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import ThreadDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", threadId: "th1" }),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { getThreadMock, listMessagesMock, listTemplatesMock } = vi.hoisted(() => ({
  getThreadMock: vi.fn(),
  listMessagesMock: vi.fn(),
  listTemplatesMock: vi.fn(),
}));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return {
    ...actual,
    getThread: getThreadMock,
    listMessages: listMessagesMock,
    listTemplates: listTemplatesMock,
  };
});

const { getContactMock } = vi.hoisted(() => ({ getContactMock: vi.fn() }));
vi.mock("@/lib/api/crm", () => ({ getContact: getContactMock }));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ThreadDetailPage", () => {
  it("renders the real thread and its contact once fetched by id", async () => {
    getThreadMock.mockResolvedValue({
      id: "th1",
      tenant_id: "tenant-1",
      contact_id: "c1",
      channel: "email",
      assigned_to_user_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    getContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });
    listMessagesMock.mockResolvedValue({ results: [], hasMore: false });
    listTemplatesMock.mockResolvedValue([]);

    render(<ThreadDetailPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Jane Doe" })).toBeInTheDocument());
    expect(getThreadMock).toHaveBeenCalledWith("tenant-1", "th1");
  });

  it("shows the non-enumerating permission-denied state on a 403/404 thread fetch", async () => {
    getThreadMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));

    render(<ThreadDetailPage />);

    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("shows the session-expired state on a 401", async () => {
    getThreadMock.mockRejectedValue(new ApiError("unauthorized", "session expired", { status: 401 }));

    render(<ThreadDetailPage />);

    await waitFor(() => expect(screen.getByText("Your session has expired")).toBeInTheDocument());
  });
});
