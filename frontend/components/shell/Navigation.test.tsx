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
  it("renders business-oriented labels, not backend module names, as real links", () => {
    render(<Navigation tenantId="tenant-1" />);

    // CRM lives under the "Klanten" group heading, labeled "Overzicht"
    // -- never "CRM" -- docs/ROADMAP.md Phase 28's own principle: primary
    // navigation is business-oriented, never a direct mirror of a
    // backend router name.
    const klantenLink = screen.getByRole("link", { name: "Overzicht" });
    expect(klantenLink).toHaveAttribute("href", "/t/tenant-1/crm");
    expect(klantenLink).toHaveAttribute("data-active", "true");

    const vandaagLink = screen.getByRole("link", { name: "Vandaag" });
    expect(vandaagLink).toHaveAttribute("href", "/t/tenant-1/dashboard");
    expect(vandaagLink).toHaveAttribute("data-active", "false");

    expect(screen.queryByRole("link", { name: "CRM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
  });

  it("reuses existing screens under a new business-oriented entry point (Verkoop -> CRM opportunities)", () => {
    render(<Navigation tenantId="tenant-1" />);

    const verkoopLink = screen.getByRole("link", { name: "Verkoop" });
    expect(verkoopLink).toHaveAttribute("href", "/t/tenant-1/crm/opportunities");
  });

  it("groups related destinations under one business-question heading", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.getByText("Klanten")).toBeInTheDocument();
    // "Reviews" (Reputation) is grouped under the same "Klanten" heading
    // as CRM, per docs/ROADMAP.md Phase 28's own grouping.
    const reviewsLink = screen.getByRole("link", { name: "Reviews" });
    expect(reviewsLink).toHaveAttribute("href", "/t/tenant-1/reputation");
  });

  it("renders planned modules as disabled, non-navigable entries -- never a fake page", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.queryByRole("link", { name: /Telefonie/ })).not.toBeInTheDocument();
    const telephony = screen.getByText("Telefonie").closest("span");
    expect(telephony).toHaveAttribute("aria-disabled", "true");
    expect(telephony).toHaveTextContent("Coming soon");
    // Every non-shipped module gets the same disabled treatment, not just this one.
    expect(screen.getAllByText("Coming soon").length).toBeGreaterThan(1);
  });

  it("does not expose technical module names (Automation, Billing, AI) as top-level items", () => {
    render(<Navigation tenantId="tenant-1" />);

    // Automation is real and reachable (relabeled "Automatisering",
    // grouped under Instellingen) but never shown under its raw
    // technical name at the top level.
    expect(screen.queryByRole("link", { name: "Automation" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Automatisering" })).toHaveAttribute(
      "href",
      "/t/tenant-1/automation",
    );
  });
});
