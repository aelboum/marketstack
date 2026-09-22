import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SettingsShell, SettingsNavigation, SettingsSection } from "./SettingsShell";

const { usePathnameMock } = vi.hoisted(() => ({ usePathnameMock: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: usePathnameMock }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("SettingsShell: replaceable settings layout", () => {
  it("renders the same settings-page subtree in the sidebar variant", () => {
    usePathnameMock.mockReturnValue("/t/t1/settings");
    render(
      <SettingsShell tenantId="t1" variant="sidebar">
        <p>settings page content</p>
      </SettingsShell>,
    );

    expect(screen.getByTestId("settings-shell")).toHaveAttribute("data-settings-layout", "sidebar");
    expect(screen.getByTestId("settings-main")).toHaveTextContent("settings page content");
  });

  it("renders the identical subtree in the tabs variant -- only the layout attribute differs", () => {
    usePathnameMock.mockReturnValue("/t/t1/settings");

    const { getByTestId: getSidebar, unmount } = render(
      <SettingsShell tenantId="t1" variant="sidebar">
        <p>settings page content</p>
      </SettingsShell>,
    );
    const sidebarMain = getSidebar("settings-main").innerHTML;
    unmount();

    render(
      <SettingsShell tenantId="t1" variant="tabs">
        <p>settings page content</p>
      </SettingsShell>,
    );
    expect(screen.getByTestId("settings-shell")).toHaveAttribute("data-settings-layout", "tabs");
    // The page's own subtree is byte-identical across both variants --
    // the concrete meaning of "a settings page owns no layout decision".
    expect(screen.getByTestId("settings-main").innerHTML).toBe(sidebarMain);
  });
});

describe("SettingsNavigation", () => {
  it("marks the current area active and links the rest, tenant-scoped", () => {
    usePathnameMock.mockReturnValue("/t/t1/settings/access");
    render(<SettingsNavigation tenantId="t1" />);

    const access = screen.getByRole("link", { name: /Toegang/ });
    expect(access).toHaveAttribute("data-active", "true");
    expect(access).toHaveAttribute("aria-current", "page");
    expect(access).toHaveAttribute("href", "/t/t1/settings/access");

    expect(screen.getByRole("link", { name: /Bedrijf/ })).toHaveAttribute("data-active", "false");
    expect(screen.getByRole("link", { name: /Profile/ })).toHaveAttribute(
      "href",
      "/t/t1/settings/profile",
    );
    expect(screen.getByRole("link", { name: /Support access/ })).toHaveAttribute(
      "href",
      "/t/t1/settings/support-access",
    );
  });

  it("does not mark Bedrijf active on a deeper settings route", () => {
    usePathnameMock.mockReturnValue("/t/t1/settings/branding");
    render(<SettingsNavigation tenantId="t1" />);

    expect(screen.getByRole("link", { name: /Bedrijf/ })).toHaveAttribute("data-active", "false");
    expect(screen.getByRole("link", { name: /Branding/ })).toHaveAttribute("data-active", "true");
  });

  it("labels an area with no backend contract in text, not by color alone", () => {
    usePathnameMock.mockReturnValue("/t/t1/settings");
    render(<SettingsNavigation tenantId="t1" />);

    expect(screen.getByRole("link", { name: /Branding/ })).toHaveTextContent("Not available");
  });

  it("builds every href from the tenant in the route, never a stored id", () => {
    usePathnameMock.mockReturnValue("/t/other-tenant/settings");
    render(<SettingsNavigation tenantId="other-tenant" />);

    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toMatch(/^\/t\/other-tenant\/settings/);
    }
  });
});

describe("SettingsSection", () => {
  it("renders a real heading that names the section for assistive tech", () => {
    usePathnameMock.mockReturnValue("/t/t1/settings");
    render(
      <SettingsSection title="Workspace" description="Identity of this workspace.">
        <p>body</p>
      </SettingsSection>,
    );

    const heading = screen.getByRole("heading", { level: 2, name: "Workspace" });
    expect(heading).toBeInTheDocument();
    // The section is associated with its own heading, so screen-reader
    // region navigation announces it.
    expect(screen.getByRole("region", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByText("Identity of this workspace.")).toBeInTheDocument();
  });
});
