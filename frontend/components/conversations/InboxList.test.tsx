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
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const ITEM = {
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
};

describe("InboxList", () => {
  it("shows loading, then real inbox items with a resolved contact name and a needs-reply badge", async () => {
    listInboxMock.mockResolvedValue([ITEM]);
    getContactMock.mockResolvedValue({ id: "c1", first_name: "Jane", last_name: "Doe" });

    render(<InboxList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    const table = screen.getByRole("table");
    expect(within(table).getByText("Wacht op reactie")).toBeInTheDocument();
    expect(screen.getByText("Hallo, kan ik een afspraak inplannen?")).toBeInTheDocument();
    expect(within(table).getByText("Niet toegewezen")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Jane Doe/ })).toHaveAttribute(
      "href",
      "/t/t1/conversations/th1",
    );
  });

  it("never shows the raw contact_id -- a neutral placeholder while resolving, 'Onbekende klant' on failure", async () => {
    listInboxMock.mockResolvedValue([ITEM]);
    getContactMock.mockRejectedValue(new ApiError("not_found", "gone", { status: 404 }));

    render(<InboxList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Onbekende klant")).toBeInTheDocument());
    expect(screen.queryByText("c1")).not.toBeInTheDocument();
  });

  it("shows an honest empty state when a filter matches nothing", async () => {
    listInboxMock.mockResolvedValue([]);
    render(<InboxList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Niets te zien hier")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listInboxMock.mockRejectedValue(new ApiError("forbidden", "not found, or no access", { status: 404 }));
    render(<InboxList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("filter buttons drive the assigned/needs_reply query params, never a client-side re-filter", async () => {
    listInboxMock.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<InboxList tenantId="t1" />);
    await waitFor(() =>
      expect(listInboxMock).toHaveBeenCalledWith("t1", {
        assigned: undefined,
        channel: undefined,
        needs_reply: undefined,
      }),
    );

    await user.click(screen.getByRole("button", { name: "Wacht op reactie" }));
    await waitFor(() =>
      expect(listInboxMock).toHaveBeenCalledWith("t1", {
        assigned: undefined,
        channel: undefined,
        needs_reply: true,
      }),
    );

    await user.click(screen.getByRole("button", { name: "Toegewezen aan mij" }));
    await waitFor(() =>
      expect(listInboxMock).toHaveBeenCalledWith("t1", {
        assigned: "me",
        channel: undefined,
        needs_reply: undefined,
      }),
    );
  });

  it("channel filter is a real server-side query param", async () => {
    listInboxMock.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<InboxList tenantId="t1" />);
    await waitFor(() => expect(listInboxMock).toHaveBeenCalled());

    await user.selectOptions(screen.getByLabelText("Kanaal"), "whatsapp");
    await waitFor(() =>
      expect(listInboxMock).toHaveBeenCalledWith("t1", {
        assigned: undefined,
        channel: "whatsapp",
        needs_reply: undefined,
      }),
    );
  });

  it("re-fetches when reloadKey changes, without user interaction", async () => {
    listInboxMock.mockResolvedValue([]);
    const { rerender } = render(<InboxList tenantId="t1" reloadKey={0} />);
    await waitFor(() => expect(listInboxMock).toHaveBeenCalledTimes(1));

    rerender(<InboxList tenantId="t1" reloadKey={1} />);
    await waitFor(() => expect(listInboxMock).toHaveBeenCalledTimes(2));
  });
});
