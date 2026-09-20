import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MessageList } from "./MessageList";
import { ApiError } from "@/lib/api/errors";

const { listMessagesMock } = vi.hoisted(() => ({ listMessagesMock: vi.fn() }));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return { ...actual, listMessages: listMessagesMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("MessageList", () => {
  it("renders messages with direction/internal-note badges", async () => {
    listMessagesMock.mockResolvedValue({
      results: [
        {
          id: "m1",
          tenant_id: "t1",
          thread_id: "th1",
          direction: "inbound",
          is_internal_note: false,
          body: "Hello there",
          author_user_id: null,
          sequence: 1,
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "m2",
          tenant_id: "t1",
          thread_id: "th1",
          direction: "outbound",
          is_internal_note: true,
          body: "Internal only",
          author_user_id: "u1",
          sequence: 2,
          created_at: "2026-01-01T00:01:00Z",
        },
      ],
      hasMore: false,
    });

    render(<MessageList tenantId="t1" threadId="th1" />);

    await waitFor(() => expect(screen.getByText("Hello there")).toBeInTheDocument());
    expect(screen.getByText("Inbound")).toBeInTheDocument();
    expect(screen.getByText("Internal note")).toBeInTheDocument();
    expect(screen.getByText("Internal only")).toBeInTheDocument();
  });

  it("renders a message body containing markup as literal text -- never executes it", async () => {
    listMessagesMock.mockResolvedValue({
      results: [
        {
          id: "m1",
          tenant_id: "t1",
          thread_id: "th1",
          direction: "inbound",
          is_internal_note: false,
          body: "<script>window.__pwned = true</script><img src=x onerror=alert(1)>",
          author_user_id: null,
          sequence: 1,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      hasMore: false,
    });

    render(<MessageList tenantId="t1" threadId="th1" />);

    await waitFor(() => expect(screen.getByText(/window\.__pwned/)).toBeInTheDocument());
    // No actual <script>/<img> element was created from the message body.
    expect(document.querySelector("script[src]")).toBeNull();
    expect(document.querySelector("img")).toBeNull();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("bounds a very long message body behind a Show more toggle without discarding it", async () => {
    const longBody = "x".repeat(1000);
    listMessagesMock.mockResolvedValue({
      results: [
        {
          id: "m1",
          tenant_id: "t1",
          thread_id: "th1",
          direction: "inbound",
          is_internal_note: false,
          body: longBody,
          author_user_id: null,
          sequence: 1,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      hasMore: false,
    });

    render(<MessageList tenantId="t1" threadId="th1" />);
    await waitFor(() => expect(screen.getByText(longBody)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
  });

  it("shows loading then empty state with no messages", async () => {
    listMessagesMock.mockResolvedValue({ results: [], hasMore: false });
    render(<MessageList tenantId="t1" threadId="th1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("No messages yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listMessagesMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<MessageList tenantId="t1" threadId="th1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
