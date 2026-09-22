import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import DashboardPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/tenant-1/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ status: "authenticated", user: { user_id: "user-1" }, markSessionExpired: vi.fn() }),
}));

vi.mock("@/lib/tenant/tenant-context", () => ({
  useTenant: () => ({ tenantId: "tenant-1" }),
}));

const {
  listClientsMock,
  loadAutomationActivityMock,
  loadTodaysAppointmentsMock,
  loadRecentContactsMock,
  listApprovalsMock,
  listInboxMock,
} = vi.hoisted(() => ({
  listClientsMock: vi.fn(),
  loadAutomationActivityMock: vi.fn(),
  loadTodaysAppointmentsMock: vi.fn(),
  loadRecentContactsMock: vi.fn(),
  listApprovalsMock: vi.fn(),
  listInboxMock: vi.fn(),
}));

vi.mock("@/lib/api/agency", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/agency")>();
  return { ...actual, listClients: listClientsMock };
});

vi.mock("@/lib/dashboard/commandCenter", () => ({
  loadAutomationActivity: loadAutomationActivityMock,
  loadTodaysAppointments: loadTodaysAppointmentsMock,
  loadRecentContacts: loadRecentContactsMock,
}));

vi.mock("@/lib/api/approvals", () => ({
  listApprovals: listApprovalsMock,
}));

vi.mock("@/lib/api/conversations", () => ({
  listInbox: listInboxMock,
}));

function setDefaultMocks() {
  listClientsMock.mockResolvedValue([]);
  loadAutomationActivityMock.mockResolvedValue({ failed: [], recentlyCompleted: [] });
  loadTodaysAppointmentsMock.mockResolvedValue([]);
  loadRecentContactsMock.mockResolvedValue([]);
  listApprovalsMock.mockResolvedValue([]);
  listInboxMock.mockResolvedValue([]);
}

describe("DashboardPage (Vandaag / Command Center)", () => {
  it("renders the business-oriented heading, not the old technical one", async () => {
    setDefaultMocks();
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "Vandaag" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
    expect(screen.getByText(/user-1/)).toBeInTheDocument();
    expect(screen.getByText(/tenant-1/)).toBeInTheDocument();
  });

  it("shows an honest empty state per section when there is genuinely nothing -- never a fabricated metric", async () => {
    setDefaultMocks();
    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("Alles in orde")).toBeInTheDocument());
    expect(screen.getByText("Geen afspraken vandaag")).toBeInTheDocument();
    expect(screen.getByText("Nog geen recente activiteit")).toBeInTheDocument();

    // No invented KPI/metric text anywhere on the page.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/MRR|revenue|conversion/i)).not.toBeInTheDocument();
  });

  it("shows real failed-automation attention items, not a placeholder", async () => {
    setDefaultMocks();
    loadAutomationActivityMock.mockResolvedValue({
      failed: [
        {
          id: "run-1",
          workflow_id: "wf-1",
          workflowName: "Follow up with new leads",
          status: "failed",
          error: "The email provider rejected the message.",
          created_at: "2026-06-10T09:00:00Z",
          completed_at: null,
        },
      ],
      recentlyCompleted: [],
    });

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByTestId("attention-list")).toBeInTheDocument());
    expect(screen.getByText("Follow up with new leads")).toBeInTheDocument();
    expect(screen.getByText("The email provider rejected the message.")).toBeInTheDocument();
  });

  it("shows a real pending-approvals count with a link into the Approval Inbox (Phase 29)", async () => {
    setDefaultMocks();
    listApprovalsMock.mockResolvedValue([{ id: "a1" }, { id: "a2" }]);

    render(<DashboardPage />);

    const link = await screen.findByRole("link", { name: /2 acties wachten op goedkeuring/ });
    expect(link).toHaveAttribute("href", "/t/tenant-1/approvals");
  });

  it("shows no pending-approvals line when there genuinely are none -- never a fabricated count", async () => {
    setDefaultMocks();

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("Alles in orde")).toBeInTheDocument());
    expect(screen.queryByText(/wachten op goedkeuring/)).not.toBeInTheDocument();
  });

  it("shows a real needs-reply inbox count with a link into the Unified Inbox (Phase 30)", async () => {
    setDefaultMocks();
    listInboxMock.mockResolvedValue([{ thread_id: "t1" }, { thread_id: "t2" }]);

    render(<DashboardPage />);

    const link = await screen.findByRole("link", { name: /2 gesprekken wachten op een reactie/ });
    expect(link).toHaveAttribute("href", "/t/tenant-1/conversations");
    expect(listInboxMock).toHaveBeenCalledWith("tenant-1", { needs_reply: true });
  });

  it("shows no needs-reply line when there genuinely are none -- never a fabricated count", async () => {
    setDefaultMocks();

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("Alles in orde")).toBeInTheDocument());
    expect(screen.queryByText(/wachten op een reactie/)).not.toBeInTheDocument();
  });

  it("composes CRM and Automation data together in one real cross-domain section", async () => {
    setDefaultMocks();
    loadRecentContactsMock.mockResolvedValue([
      { id: "c1", first_name: "Jamie", last_name: "Vos", created_at: "2026-06-09T10:00:00Z" },
    ]);
    loadAutomationActivityMock.mockResolvedValue({
      failed: [],
      recentlyCompleted: [
        {
          id: "run-2",
          workflow_id: "wf-2",
          workflowName: "Send booking confirmation",
          status: "completed",
          completed_at: "2026-06-09T11:00:00Z",
        },
      ],
    });

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByTestId("recent-activity-list")).toBeInTheDocument());
    expect(screen.getByText(/Jamie Vos/)).toBeInTheDocument();
    expect(screen.getByText(/Send booking confirmation/)).toBeInTheDocument();
  });

  it("keeps the real client-business list and invite-teammate flow (existing functionality, not removed)", async () => {
    setDefaultMocks();
    listClientsMock.mockResolvedValue([{ tenant_id: "c1", name: "Acme Dental" }]);

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("Acme Dental")).toBeInTheDocument());

    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Invite teammate" }));
    expect(screen.getByRole("dialog", { name: "Invite a teammate" })).toBeInTheDocument();
  });
});
