import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Navigation } from "./Navigation";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/tenant-1/crm",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("Navigation", () => {
  it("renders available modules as real links, with the current route marked active", () => {
    render(<Navigation tenantId="tenant-1" />);

    const crmLink = screen.getByRole("link", { name: "CRM" });
    expect(crmLink).toHaveAttribute("href", "/t/tenant-1/crm");
    expect(crmLink).toHaveAttribute("data-active", "true");

    const dashboardLink = screen.getByRole("link", { name: "Dashboard" });
    expect(dashboardLink).toHaveAttribute("data-active", "false");
  });

  it("renders planned modules as disabled, non-navigable entries -- never a fake page", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.queryByRole("link", { name: /Telephony/ })).not.toBeInTheDocument();
    const telephony = screen.getByText("Telephony").closest("span");
    expect(telephony).toHaveAttribute("aria-disabled", "true");
    expect(telephony).toHaveTextContent("Coming soon");
    // Every non-shipped module gets the same disabled treatment, not just this one.
    expect(screen.getAllByText("Coming soon").length).toBeGreaterThan(1);
  });
});
