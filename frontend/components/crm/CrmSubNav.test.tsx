import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CrmSubNav } from "./CrmSubNav";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/tenant-1/crm/contacts",
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("CrmSubNav", () => {
  it("marks the current section active and links the rest", () => {
    render(<CrmSubNav tenantId="tenant-1" />);

    expect(screen.getByRole("link", { name: "Contacts" })).toHaveAttribute("data-active", "true");
    expect(screen.getByRole("link", { name: "Companies" })).toHaveAttribute("data-active", "false");
    expect(screen.getByRole("link", { name: "Opportunities" })).toHaveAttribute(
      "href",
      "/t/tenant-1/crm/opportunities",
    );
    expect(screen.getByRole("link", { name: "Pipelines" })).toHaveAttribute(
      "href",
      "/t/tenant-1/crm/pipelines",
    );
  });
});
