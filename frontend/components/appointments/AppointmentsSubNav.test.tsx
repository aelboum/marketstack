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
    expect(screen.getByRole("link", { name: "Overzicht" })).toHaveAttribute("data-active", "false");
    expect(screen.getByRole("link", { name: "Overzicht" })).toHaveAttribute(
      "href",
      "/t/tenant-1/appointments",
    );
    expect(screen.getByRole("link", { name: "Calendars" })).toHaveAttribute(
      "href",
      "/t/tenant-1/appointments/calendars",
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

  it("names no tab literally 'Appointments' -- the business-oriented label is 'Overzicht'", () => {
    render(<AppointmentsSubNav tenantId="tenant-1" />);
    expect(screen.queryByRole("link", { name: "Appointments" })).not.toBeInTheDocument();
  });
});
