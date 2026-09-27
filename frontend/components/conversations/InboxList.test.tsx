import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InboxList } from "./InboxList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/t1/conversations",
}));

const { listInboxMock, getContactMock } = vi.hoisted(() => ({
  listInboxMock: vi.fn(),
  getContactMock: vi.fn(),
}));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return { ...actual, listInbox: listInboxMock };
});
vi.mock("@/lib/api/crm", () => ({ getContact: getContactMock }));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ user: { user_id: "me-1" }, markSessionExpired: vi.fn() }),
}));

function item(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    thread_id: "th1",
    tenant_id: "t1",
    contact_id: "c1",
    channel: "email" as const,
    assigned_to_user_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_message_preview: "Hallo, kan ik een afspraak inplannen?",
    last_message_at: "2026-01-01T09:00:00Z",
    last_message_direction: "inbound" as const,
    last_message_is_internal_note: false,
    needs_reply: true,
    ...overrides,
  };
}

describe("InboxList", () => {
  it("shows loading, then a real inbox row with a resolved contact name, linking to the thread", async () => {
    listInboxMock.mockResolvedValue([item()]);
    getContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });

    render(<InboxList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(screen.getByText("Hallo, kan ik een afspraak inplannen?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Jane Doe/ })).toHaveAttribute(
      "href",
      "/t/t1/conversations/th1",
    );
    // One bounded, unfiltered fetch backs the list and all three chip
    // counts -- never a per-filter server round trip.
    expect(listInboxMock).toHaveBeenCalledWith("t1", { limit: 100 });
  });

  it("never shows the raw contact_id -- a neutral placeholder while resolving, 'Onbekende klant' on failure", async () => {
    listInboxMock.mockResolvedValue([item()]);
    getContactMock.mockRejectedValue(new ApiError("not_found", "gone", { status: 404 }));

    render(<InboxList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Onbekende klant")).toBeInTheDocument());
    expect(screen.queryByText("c1")).not.toBeInTheDocument();
  });

  it("shows an honest empty state when there are genuinely no conversations", async () => {
    listInboxMock.mockResolvedValue([]);
    render(<InboxList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Je bent helemaal bij")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listInboxMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<InboxList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("filters the already-loaded list client-side by chip, with real per-chip counts", async () => {
    listInboxMock.mockResolvedValue([
      item({ thread_id: "th1", contact_id: "c1", needs_reply: true, assigned_to_user_id: null }),
      item({ thread_id: "th2", contact_id: "c2", needs_reply: false, assigned_to_user_id: "me-1" }),
      item({ thread_id: "th3", contact_id: "c3", needs_reply: false, assigned_to_user_id: "other-1" }),
    ]);
    getContactMock.mockImplementation((_tenantId: string, id: string) =>
      Promise.resolve({ id, first_name: id, last_name: "Doe" }),
    );
    const user = userEvent.setup();

    render(<InboxList tenantId="t1" />);
    await waitFor(() => expect(screen.getAllByRole("link").length).toBe(3));

    const unreadChip = screen.getByRole("button", { name: /Ongelezen/ });
    expect(within(unreadChip).getByText("1")).toBeInTheDocument();
    const mineChip = screen.getByRole("button", { name: /Van mij/ });
    expect(within(mineChip).getByText("1")).toBeInTheDocument();

    await user.click(unreadChip);
    await waitFor(() => expect(screen.getAllByRole("link").length).toBe(1));
    expect(screen.getByText("c1 Doe")).toBeInTheDocument();

    await user.click(mineChip);
    await waitFor(() => expect(screen.getAllByRole("link").length).toBe(1));
    expect(screen.getByText("c2 Doe")).toBeInTheDocument();

    // Switching chips never re-fetches -- one load backs every chip.
    expect(listInboxMock).toHaveBeenCalledTimes(1);
  });

  it("re-fetches when reloadKey changes, without user interaction", async () => {
    listInboxMock.mockResolvedValue([]);
    const { rerender } = render(<InboxList tenantId="t1" reloadKey={0} />);
    await waitFor(() => expect(listInboxMock).toHaveBeenCalledTimes(1));

    rerender(<InboxList tenantId="t1" reloadKey={1} />);
    await waitFor(() => expect(listInboxMock).toHaveBeenCalledTimes(2));
  });
});
