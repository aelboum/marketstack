import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }));
vi.mock("./client", () => ({ request: requestMock }));

import {
  bookAppointment,
  cancelAppointment,
  createAvailabilityRule,
  createCalendar,
  deleteAvailabilityRule,
  deleteCalendar,
  getCalendar,
  getOrCreateBookingLink,
  listAppointments,
  listAvailabilityRules,
  listAvailableSlots,
  listCalendars,
  rescheduleAppointment,
  sweepReminders,
  updateCalendar,
} from "./appointments";

describe("appointments API functions -- exact request shape sent to the real routes", () => {
  beforeEach(() => {
    requestMock.mockReset();
  });

  it("listCalendars() -> GET with limit/offset only (no filter exists on this endpoint)", async () => {
    requestMock.mockResolvedValue([{ id: "c1" }]);
    const result = await listCalendars("t1", { limit: 25, offset: 0 });
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/calendars", {
      query: { limit: 25, offset: 0 },
    });
    expect(result.hasMore).toBe(false);
  });

  it("listAppointments() -> GET with starts_after/starts_before/limit/offset", async () => {
    requestMock.mockResolvedValue([{ id: "a1" }]);
    const result = await listAppointments("t1", {
      starts_after: "2026-06-10T00:00:00Z",
      starts_before: "2026-06-11T00:00:00Z",
    });
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/appointments", {
      query: {
        starts_after: "2026-06-10T00:00:00Z",
        starts_before: "2026-06-11T00:00:00Z",
        limit: 25,
        offset: 0,
      },
    });
    expect(result.hasMore).toBe(false);
  });

  it("getCalendar() -> GET /calendars/{id}", async () => {
    requestMock.mockResolvedValue({});
    await getCalendar("t1", "cal1");
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/calendars/cal1");
  });

  it("createCalendar() -> POST with name/owner_user_id/timezone", async () => {
    requestMock.mockResolvedValue({});
    await createCalendar("t1", { name: "Sales", owner_user_id: "u1", timezone: "Europe/Amsterdam" });
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/calendars", {
      method: "POST",
      body: { name: "Sales", owner_user_id: "u1", timezone: "Europe/Amsterdam" },
    });
  });

  it("updateCalendar() -> PATCH (null means leave unchanged, per the backend)", async () => {
    requestMock.mockResolvedValue({});
    await updateCalendar("t1", "cal1", { name: "Renamed", owner_user_id: null, timezone: null });
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/calendars/cal1", {
      method: "PATCH",
      body: { name: "Renamed", owner_user_id: null, timezone: null },
    });
  });

  it("deleteCalendar() -> DELETE", async () => {
    requestMock.mockResolvedValue(undefined);
    await deleteCalendar("t1", "cal1");
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/calendars/cal1", {
      method: "DELETE",
    });
  });

  it("getOrCreateBookingLink() -> POST .../booking-link", async () => {
    requestMock.mockResolvedValue({ link_token: "tok" });
    await getOrCreateBookingLink("t1", "cal1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/appointments/tenants/t1/calendars/cal1/booking-link",
      { method: "POST" },
    );
  });

  it("listAvailabilityRules() -> GET with no pagination params (the route has none)", async () => {
    requestMock.mockResolvedValue([]);
    await listAvailabilityRules("t1", "cal1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/appointments/tenants/t1/calendars/cal1/availability-rules",
    );
  });

  it("createAvailabilityRule() -> POST with day_of_week/start_time/end_time", async () => {
    requestMock.mockResolvedValue({});
    await createAvailabilityRule("t1", "cal1", { day_of_week: 0, start_time: 540, end_time: 1020 });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/appointments/tenants/t1/calendars/cal1/availability-rules",
      { method: "POST", body: { day_of_week: 0, start_time: 540, end_time: 1020 } },
    );
  });

  it("deleteAvailabilityRule() -> DELETE the calendar-scoped rule path", async () => {
    requestMock.mockResolvedValue(undefined);
    await deleteAvailabilityRule("t1", "cal1", "r1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/appointments/tenants/t1/calendars/cal1/availability-rules/r1",
      { method: "DELETE" },
    );
  });

  it("listAvailableSlots() -> GET with date_from/date_to/slot_duration_minutes", async () => {
    requestMock.mockResolvedValue([]);
    await listAvailableSlots("t1", "cal1", {
      date_from: "2026-03-01",
      date_to: "2026-03-07",
      slot_duration_minutes: 30,
    });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/appointments/tenants/t1/calendars/cal1/available-slots",
      { query: { date_from: "2026-03-01", date_to: "2026-03-07", slot_duration_minutes: 30 } },
    );
  });

  it("bookAppointment() -> POST .../appointments with the contact + slot fields", async () => {
    requestMock.mockResolvedValue({});
    await bookAppointment("t1", {
      calendar_id: "cal1",
      contact_email: "a@example.com",
      contact_first_name: "A",
      contact_last_name: "B",
      contact_phone: null,
      starts_at: "2026-03-01T09:00:00.000Z",
      ends_at: "2026-03-01T09:30:00.000Z",
    });
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/appointments", {
      method: "POST",
      body: {
        calendar_id: "cal1",
        contact_email: "a@example.com",
        contact_first_name: "A",
        contact_last_name: "B",
        contact_phone: null,
        starts_at: "2026-03-01T09:00:00.000Z",
        ends_at: "2026-03-01T09:30:00.000Z",
      },
    });
  });

  it("cancelAppointment() -> POST .../cancel with no body", async () => {
    requestMock.mockResolvedValue({});
    await cancelAppointment("t1", "a1");
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/appointments/tenants/t1/appointments/a1/cancel",
      { method: "POST" },
    );
  });

  it("rescheduleAppointment() -> POST .../reschedule with new_starts_at/new_ends_at", async () => {
    requestMock.mockResolvedValue({});
    await rescheduleAppointment("t1", "a1", {
      new_starts_at: "2026-03-02T09:00:00.000Z",
      new_ends_at: "2026-03-02T09:30:00.000Z",
    });
    expect(requestMock).toHaveBeenCalledWith(
      "/v1/appointments/tenants/t1/appointments/a1/reschedule",
      {
        method: "POST",
        body: {
          new_starts_at: "2026-03-02T09:00:00.000Z",
          new_ends_at: "2026-03-02T09:30:00.000Z",
        },
      },
    );
  });

  it("sweepReminders() -> POST .../reminders/sweep", async () => {
    requestMock.mockResolvedValue({ reminded_count: 0, appointment_ids: [] });
    await sweepReminders("t1");
    expect(requestMock).toHaveBeenCalledWith("/v1/appointments/tenants/t1/reminders/sweep", {
      method: "POST",
    });
  });
});
