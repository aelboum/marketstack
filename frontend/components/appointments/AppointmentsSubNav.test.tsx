import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AppointmentsSubNav } from "./AppointmentsSubNav";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/tenant-1/appointments/book",
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("AppointmentsSubNav", () => {
  it("marks the current section active and links the rest", () => {
    render(<AppointmentsSubNav tenantId="tenant-1" />);

    expect(screen.getByRole("link", { name: "Book" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("link", { name: "Calendars" })).toHaveAttribute("data-active", "false");
    expect(screen.getByRole("link", { name: "Calendars" })).toHaveAttribute(
      "href",
      "/t/tenant-1/appointments",
    );
    expect(screen.getByRole("link", { name: "Manage" })).toHaveAttribute(
      "href",
      "/t/tenant-1/appointments/manage",
    );
    expect(screen.getByRole("link", { name: "Reminders" })).toHaveAttribute(
      "href",
      "/t/tenant-1/appointments/reminders",
    );
  });

  it("offers no appointment-list tab -- the backend exposes no list endpoint", () => {
    render(<AppointmentsSubNav tenantId="tenant-1" />);
    expect(screen.queryByRole("link", { name: "Appointments" })).not.toBeInTheDocument();
  });
});
