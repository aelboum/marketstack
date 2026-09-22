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

vi.mock("@/lib/i18n/locale-context", () => ({
  useLocale: () => ({ locale: "NL" as const, setLocale: vi.fn() }),
}));

const PRIMARY_LABELS = [
  "Dashboard",
  "Inbox",
  "Klanten",
  "Verkoop",
  "Agenda",
  "Groei",
  "Automatiseringen",
  "Boekhouding",
  "Reputatie",
  "AI",
  "Beheer",
];

describe("Navigation (approved 11-item IA)", () => {
  it("renders exactly the 11 approved primary items, in the approved order, with the approved labels", () => {
    render(<Navigation tenantId="tenant-1" />);

    const nav = screen.getByRole("navigation", { name: "Product navigation" });
    // `:scope > ul` -- the top-level list only; several items also
    // render their own nested `<ul>` of children, which would make a
    // role-based "list" query ambiguous.
    const outerList = nav.querySelector(":scope > ul");
    expect(outerList).not.toBeNull();
    const topLevel = outerList!.children;
    expect(topLevel).toHaveLength(11);

    const renderedLabels = Array.from(topLevel).map((li) => li.textContent?.split("Coming soon")[0].trim());
    // Each rendered label starts with the approved label (children add
    // more text after it, which the split above strips off).
    PRIMARY_LABELS.forEach((label, index) => {
      expect(renderedLabels[index]?.startsWith(label)).toBe(true);
    });
  });

  it("uses the plural 'Automatiseringen', never the old singular, as a real link to /automation", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.queryByRole("link", { name: "Automatisering" })).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Automatiseringen" });
    expect(link).toHaveAttribute("href", "/t/tenant-1/automation");
  });

  it("labels the AI item exactly 'AI', never 'AI-assistent', as a disabled Coming-soon entry", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.queryByText("AI-assistent")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "AI" })).not.toBeInTheDocument();
    const ai = screen.getByText("AI").closest("span");
    expect(ai).toHaveAttribute("aria-disabled", "true");
    expect(ai).toHaveTextContent("Coming soon");
  });

  it("Klanten, Verkoop, Agenda, Reputatie are real top-level links to their existing routes", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.getByRole("link", { name: "Klanten" })).toHaveAttribute("href", "/t/tenant-1/crm");
    expect(screen.getByRole("link", { name: "Verkoop" })).toHaveAttribute(
      "href",
      "/t/tenant-1/crm/opportunities",
    );
    expect(screen.getByRole("link", { name: "Agenda" })).toHaveAttribute("href", "/t/tenant-1/appointments");
    expect(screen.getByRole("link", { name: "Reputatie" })).toHaveAttribute("href", "/t/tenant-1/reputation");
  });

  it("keeps Goedkeuringen, Instellingen and Klantbedrijven real and reachable, reorganized under Beheer", () => {
    render(<Navigation tenantId="tenant-1" />);

    // "Beheer" itself is a heading, not a link -- it organizes real
    // children rather than being a destination of its own.
    expect(screen.queryByRole("link", { name: "Beheer" })).not.toBeInTheDocument();
    expect(screen.getByText("Beheer")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Goedkeuringen" })).toHaveAttribute(
      "href",
      "/t/tenant-1/approvals",
    );
    expect(screen.getByRole("link", { name: "Instellingen" })).toHaveAttribute("href", "/t/tenant-1/settings");
    expect(screen.getByRole("link", { name: "Klantbedrijven" })).toHaveAttribute(
      "href",
      "/t/tenant-1/clients",
    );

    // None of the three appear a second time as their own top-level
    // primary item -- the approved IA names exactly 11 primary labels.
    expect(PRIMARY_LABELS).not.toContain("Goedkeuringen");
    expect(PRIMARY_LABELS).not.toContain("Instellingen");
    expect(PRIMARY_LABELS).not.toContain("Klantbedrijven");
  });

  it("keeps Marketing and Websites real and reachable, reorganized under Groei, with Prospectie honestly Coming soon", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.queryByRole("link", { name: "Groei" })).not.toBeInTheDocument();
    expect(screen.getByText("Groei")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Marketing" })).toHaveAttribute("href", "/t/tenant-1/marketing");
    expect(screen.getByRole("link", { name: "Websites" })).toHaveAttribute("href", "/t/tenant-1/websites");

    const prospecting = screen.getByText("Prospectie").closest("span");
    expect(prospecting).toHaveAttribute("aria-disabled", "true");
    expect(prospecting).toHaveTextContent("Coming soon");
  });

  it("reorganizes Telefonie under Inbox, which stays a real link itself", () => {
    render(<Navigation tenantId="tenant-1" />);

    const inboxLink = screen.getByRole("link", { name: "Inbox" });
    expect(inboxLink).toHaveAttribute("href", "/t/tenant-1/conversations");

    const telephony = screen.getByText("Telefonie").closest("span");
    expect(telephony).toHaveAttribute("aria-disabled", "true");
    expect(telephony).toHaveTextContent("Coming soon");
  });

  it("collapses Boekhouding into one disabled Coming-soon entry -- Facturatie is not shown as its own separate primary item, and no disabled child renders under an already-disabled parent", () => {
    render(<Navigation tenantId="tenant-1" />);

    const accounting = screen.getByText("Boekhouding").closest("span");
    expect(accounting).toHaveAttribute("aria-disabled", "true");
    expect(accounting).toHaveTextContent("Coming soon");

    expect(screen.queryByRole("link", { name: "Facturatie" })).not.toBeInTheDocument();
    expect(screen.queryByText("Facturatie")).not.toBeInTheDocument();
    expect(PRIMARY_LABELS).not.toContain("Facturatie");
  });

  it("renders no raw backend/technical module name anywhere", () => {
    render(<Navigation tenantId="tenant-1" />);

    expect(screen.queryByRole("link", { name: "CRM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Automation" })).not.toBeInTheDocument();
  });
});
