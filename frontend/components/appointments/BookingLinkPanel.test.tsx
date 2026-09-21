import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BookingLinkPanel } from "./BookingLinkPanel";
import { ApiError } from "@/lib/api/errors";

const { getOrCreateBookingLinkMock } = vi.hoisted(() => ({ getOrCreateBookingLinkMock: vi.fn() }));
vi.mock("@/lib/api/appointments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/appointments")>();
  return { ...actual, getOrCreateBookingLink: getOrCreateBookingLinkMock };
});

describe("BookingLinkPanel", () => {
  it("does not mint a link on render -- the route is a POST that creates one", () => {
    render(<BookingLinkPanel tenantId="t1" calendarId="cal1" />);
    expect(getOrCreateBookingLinkMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Show booking link" })).toBeInTheDocument();
  });

  it("shows the public booking URL built from the real token", async () => {
    getOrCreateBookingLinkMock.mockResolvedValue({ link_token: "tok-123" });
    const user = userEvent.setup();

    render(<BookingLinkPanel tenantId="t1" calendarId="cal1" />);
    await user.click(screen.getByRole("button", { name: "Show booking link" }));

    await waitFor(() => expect(getOrCreateBookingLinkMock).toHaveBeenCalledWith("t1", "cal1"));
    expect(screen.getByText(/\/v1\/appointments\/book\/tok-123$/)).toBeInTheDocument();
  });

  it("surfaces a backend error instead of showing a token", async () => {
    getOrCreateBookingLinkMock.mockRejectedValue(
      new ApiError("forbidden", "Not found, or you don't have access to it.", { status: 404 }),
    );
    const user = userEvent.setup();

    render(<BookingLinkPanel tenantId="t1" calendarId="cal1" />);
    await user.click(screen.getByRole("button", { name: "Show booking link" }));

    await waitFor(() =>
      expect(screen.getByText("Not found, or you don't have access to it.")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/\/v1\/appointments\/book\//)).not.toBeInTheDocument();
  });
});
