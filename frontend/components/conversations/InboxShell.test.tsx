import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { InboxShell } from "./InboxShell";

const { usePathnameMock } = vi.hoisted(() => ({ usePathnameMock: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: usePathnameMock }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listInboxMock } = vi.hoisted(() => ({ listInboxMock: vi.fn() }));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return { ...actual, listInbox: listInboxMock };
});
vi.mock("@/lib/api/crm", () => ({ getContact: vi.fn() }));
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("InboxShell: replaceable split-view layout", () => {
  it("shows the detail pane closed (list-only) on the bare inbox route", async () => {
    listInboxMock.mockResolvedValue([]);
    usePathnameMock.mockReturnValue("/t/t1/conversations");

    render(
      <InboxShell tenantId="t1">
        <p>bare inbox page</p>
      </InboxShell>,
    );

    expect(screen.getByTestId("inbox-shell")).toHaveAttribute("data-detail-open", "false");
    expect(screen.getByTestId("inbox-list-pane")).toBeInTheDocument();
    expect(screen.getByTestId("inbox-detail-pane")).toHaveTextContent("bare inbox page");
  });

  it("marks the detail pane open once a thread route is active", async () => {
    listInboxMock.mockResolvedValue([]);
    usePathnameMock.mockReturnValue("/t/t1/conversations/th1");

    render(
      <InboxShell tenantId="t1">
        <p>thread detail</p>
      </InboxShell>,
    );

    expect(screen.getByTestId("inbox-shell")).toHaveAttribute("data-detail-open", "true");
  });

  it("renders the message-templates sub-route as a plain passthrough, with no inbox list wrapped around it", async () => {
    usePathnameMock.mockReturnValue("/t/t1/conversations/templates");

    render(
      <InboxShell tenantId="t1">
        <p>templates page</p>
      </InboxShell>,
    );

    expect(screen.getByText("templates page")).toBeInTheDocument();
    expect(screen.queryByTestId("inbox-shell")).not.toBeInTheDocument();
    expect(listInboxMock).not.toHaveBeenCalled();
  });
});
