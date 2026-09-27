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

const { getContactMock, listOpportunitiesMock, listStagesMock } = vi.hoisted(() => ({
  getContactMock: vi.fn(),
  listOpportunitiesMock: vi.fn(),
  listStagesMock: vi.fn(),
}));
vi.mock("@/lib/api/crm", () => ({
  getContact: getContactMock,
  listOpportunities: listOpportunitiesMock,
  listStages: listStagesMock,
}));

const { listAppointmentsMock } = vi.hoisted(() => ({ listAppointmentsMock: vi.fn() }));
vi.mock("@/lib/api/appointments", () => ({ listAppointments: listAppointmentsMock }));

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function setCustomerPanelDefaultMocks() {
  listOpportunitiesMock.mockResolvedValue({ results: [], hasMore: false });
  listStagesMock.mockResolvedValue([]);
  listAppointmentsMock.mockResolvedValue({ results: [], hasMore: false });
}

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
    getContactMock.mockResolvedValue({
      id: "c1",
      first_name: "Jane",
      last_name: "Doe",
      email: "jane@example.com",
      phone: "+31 6 1234 5678",
      created_at: "2026-01-01T00:00:00Z",
    });
    listMessagesMock.mockResolvedValue({ results: [], hasMore: false });
    listTemplatesMock.mockResolvedValue([]);
    setCustomerPanelDefaultMocks();

    render(<ThreadDetailPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Jane Doe" })).toBeInTheDocument());
    expect(getThreadMock).toHaveBeenCalledWith("tenant-1", "th1");
  });

  it("shows an honest 'no opportunity linked' state, never a fabricated deal, when the contact has none", async () => {
    getThreadMock.mockResolvedValue({
      id: "th1",
      tenant_id: "tenant-1",
      contact_id: "c1",
      channel: "whatsapp",
      assigned_to_user_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    getContactMock.mockResolvedValue({
      id: "c1",
      first_name: "Jane",
      last_name: "Doe",
      email: null,
      phone: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    listMessagesMock.mockResolvedValue({ results: [], hasMore: false });
    listTemplatesMock.mockResolvedValue([]);
    setCustomerPanelDefaultMocks();

    render(<ThreadDetailPage />);

    await waitFor(() => expect(screen.getByText("Geen kansen gekoppeld")).toBeInTheDocument());
    expect(screen.getByText("Niets gepland")).toBeInTheDocument();
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
