import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CalendarsList } from "./CalendarsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listCalendarsMock } = vi.hoisted(() => ({ listCalendarsMock: vi.fn() }));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, listCalendars: listCalendarsMock };
});

vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function calendar(overrides: Record<string, unknown> = {}) {
  return {
    id: "cal1",
    tenant_id: "t1",
    name: "Sales calls",
    owner_user_id: "u1",
    timezone: "Europe/Amsterdam",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("CalendarsList", () => {
  it("shows loading, then real calendars linked to their detail page", async () => {
    listCalendarsMock.mockResolvedValue({ results: [calendar()], hasMore: false });

    render(<CalendarsList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Sales calls")).toBeInTheDocument());
    expect(screen.getByText("Europe/Amsterdam")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sales calls/ })).toHaveAttribute(
      "href",
      "/t/t1/appointments/calendars/cal1",
    );
  });

  it("shows an empty state with no calendars", async () => {
    listCalendarsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<CalendarsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No calendars yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listCalendarsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<CalendarsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("shows the session-expired state on 401", async () => {
    listCalendarsMock.mockRejectedValue(
      new ApiError("unauthorized", "session expired", { status: 401 }),
    );
    render(<CalendarsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Your session has expired")).toBeInTheDocument());
  });

  it("paginates via Previous/Next using limit/offset, never a fabricated total", async () => {
    listCalendarsMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => calendar({ id: `cal${i}`, name: `Cal ${i}` })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<CalendarsList tenantId="t1" />);
    await waitFor(() =>
      expect(listCalendarsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }),
    );

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(listCalendarsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 25 }),
    );
  });
});
