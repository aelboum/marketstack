import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "./AppShell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/t/tenant-1/dashboard",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// A stand-in "domain page" -- the same node is used for every layout
// below, unmodified. This is the concrete proof the UI Track roadmap
// asks for: the shell's layout can change (sidebar <-> topnav) without
// this component changing at all.
function StandInDomainPage() {
  return <div data-testid="domain-page">Contacts list would render here.</div>;
}

describe("AppShell: replaceable layout", () => {
  it.each([["sidebar"], ["topnav"]] as const)(
    "renders the exact same domain-page subtree in %s layout",
    (layout) => {
      render(
        <AppShell layout={layout} tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
          <StandInDomainPage />
        </AppShell>,
      );

      const main = screen.getByTestId("shell-main");
      expect(main).toContainElement(screen.getByTestId("domain-page"));
      expect(screen.getByTestId("domain-page")).toHaveTextContent(
        "Contacts list would render here.",
      );
    },
  );

  it("marks the active layout via data-layout, and only that attribute differs structurally", () => {
    const { rerender } = render(
      <AppShell layout="sidebar" tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
        <StandInDomainPage />
      </AppShell>,
    );
    expect(screen.getByTestId("app-shell")).toHaveAttribute("data-layout", "sidebar");
    // Sidebar layout renders one Navigation instance, outside the top bar.
    expect(screen.getAllByRole("navigation")).toHaveLength(1);

    rerender(
      <AppShell layout="topnav" tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
        <StandInDomainPage />
      </AppShell>,
    );
    expect(screen.getByTestId("app-shell")).toHaveAttribute("data-layout", "topnav");
    // Topnav layout still renders exactly one Navigation, now embedded in TopBar.
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
    expect(screen.getByTestId("domain-page")).toHaveTextContent(
      "Contacts list would render here.",
    );
  });

  it("the mobile nav toggle opens the sidebar without affecting the domain page", async () => {
    const user = userEvent.setup();
    render(
      <AppShell layout="sidebar" tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
        <StandInDomainPage />
      </AppShell>,
    );

    // The toggle is CSS-hidden above the mobile breakpoint (jsdom's
    // default viewport is desktop-sized, and this test is about the
    // click-handler wiring, not the responsive CSS itself) -- queried by
    // test id rather than role/name, since jsdom does not reliably
    // compute accessible names for elements it also considers
    // (correctly, at this simulated viewport) non-visible.
    const toggle = screen.getByTestId("mobile-nav-toggle");
    await user.click(toggle);

    const sidebar = screen.getByRole("navigation").closest("aside");
    expect(sidebar).toHaveAttribute("data-open", "true");
    expect(screen.getByTestId("domain-page")).toBeInTheDocument();
  });

  it("calls onLogout from the account menu", async () => {
    const onLogout = vi.fn();
    const user = userEvent.setup();
    render(
      <AppShell layout="sidebar" tenantId="tenant-1" userId="user-1" onLogout={onLogout}>
        <StandInDomainPage />
      </AppShell>,
    );

    await user.click(screen.getByRole("button", { name: "Account menu" }));
    await user.click(screen.getByRole("menuitem", { name: "Log out" }));
    expect(onLogout).toHaveBeenCalledOnce();
  });
});
