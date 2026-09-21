import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CalendarDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", calendarId: "cal1" }),
  useRouter: () => ({ push: pushMock }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const {
  getCalendarMock,
  deleteCalendarMock,
  listAvailabilityRulesMock,
  listAvailableSlotsMock,
  getOrCreateBookingLinkMock,
} = vi.hoisted(() => ({
  getCalendarMock: vi.fn(),
  deleteCalendarMock: vi.fn(),
  listAvailabilityRulesMock: vi.fn(),
  listAvailableSlotsMock: vi.fn(),
  getOrCreateBookingLinkMock: vi.fn(),
}));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return {
    ...actual,
    getCalendar: getCalendarMock,
    deleteCalendar: deleteCalendarMock,
    listAvailabilityRules: listAvailabilityRulesMock,
    listAvailableSlots: listAvailableSlotsMock,
    getOrCreateBookingLink: getOrCreateBookingLinkMock,
  };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ user: { user_id: "me-123" }, markSessionExpired: vi.fn() }),
}));

const CALENDAR = {
  id: "cal1",
  tenant_id: "tenant-1",
  name: "Sales calls",
  owner_user_id: "u1",
  timezone: "Europe/Amsterdam",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

describe("CalendarDetailPage", () => {
  it("renders the real calendar once fetched by id", async () => {
    getCalendarMock.mockResolvedValue(CALENDAR);
    listAvailabilityRulesMock.mockResolvedValue([]);

    render(<CalendarDetailPage />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sales calls" })).toBeInTheDocument(),
    );
    expect(getCalendarMock).toHaveBeenCalledWith("tenant-1", "cal1");
    expect(screen.getByText("u1")).toBeInTheDocument();
  });

  it("shows the non-enumerating permission-denied state on a 403/404", async () => {
    getCalendarMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<CalendarDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("shows the session-expired state on a 401", async () => {
    getCalendarMock.mockRejectedValue(
      new ApiError("unauthorized", "session expired", { status: 401 }),
    );
    render(<CalendarDetailPage />);
    await waitFor(() => expect(screen.getByText("Your session has expired")).toBeInTheDocument());
  });

  it("delete requires confirmation and navigates away only on success", async () => {
    getCalendarMock.mockResolvedValue(CALENDAR);
    listAvailabilityRulesMock.mockResolvedValue([]);
    deleteCalendarMock.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<CalendarDetailPage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sales calls" })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteCalendarMock).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(deleteCalendarMock).toHaveBeenCalledWith("tenant-1", "cal1"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/t/tenant-1/appointments"));
  });

  it("a refused delete keeps the user on the page with the error visible", async () => {
    pushMock.mockClear();
    getCalendarMock.mockResolvedValue(CALENDAR);
    listAvailabilityRulesMock.mockResolvedValue([]);
    // What a `member` (no `delete` grant) actually gets back.
    deleteCalendarMock.mockRejectedValue(
      new ApiError("forbidden", "Not found, or you don't have access to it.", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<CalendarDetailPage />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Sales calls" })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(screen.getByText("Not found, or you don't have access to it.")).toBeInTheDocument(),
    );
    expect(pushMock).not.toHaveBeenCalled();
  });
});
