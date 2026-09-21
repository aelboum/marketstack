import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "./AppShell";

// UI-8: the shell's narrow-screen and keyboard behavior. Kept in its own
// file so the UI-1 AppShell.test.tsx contract (layout replaceability)
// stays focused on what it was written to prove.

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

function renderShell() {
  return render(
    <AppShell layout="sidebar" tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
      <div data-testid="domain-page">page</div>
    </AppShell>,
  );
}

describe("AppShell accessibility (UI-8)", () => {
  it("exposes the navigation toggle's state, not just its icon", async () => {
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByTestId("mobile-nav-toggle");
    // The control is icon-only, so its whole meaning is the accessible
    // name plus the expanded state. Asserted via the attributes rather
    // than `toHaveAccessibleName`, for the reason AppShell.test.tsx
    // already documents: jsdom does not compute accessible names for
    // this element, which its CSS hides above the mobile breakpoint.
    expect(toggle).toHaveAttribute("aria-label", "Open navigation");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-label", "Close navigation");
  });

  it("points aria-controls at the element it actually controls", async () => {
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByTestId("mobile-nav-toggle");
    await user.click(toggle);

    const controlledId = toggle.getAttribute("aria-controls");
    const sidebar = screen.getByRole("navigation").closest("aside");
    expect(sidebar).not.toBeNull();
    expect(sidebar?.id).toBe(controlledId);
    expect(sidebar).toHaveAttribute("data-open", "true");
  });

  it("closes the mobile navigation on Escape and returns focus to the toggle", async () => {
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByTestId("mobile-nav-toggle");
    await user.click(toggle);
    const sidebar = screen.getByRole("navigation").closest("aside");
    expect(sidebar).toHaveAttribute("data-open", "true");

    await user.keyboard("{Escape}");

    expect(sidebar).toHaveAttribute("data-open", "false");
    // Without this, focus would fall back to <body> and the next Tab
    // would restart at the top of the document.
    expect(toggle).toHaveFocus();
  });

  it("moves focus into the navigation when it opens", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByTestId("mobile-nav-toggle"));

    const firstNavLink = screen.getAllByRole("link")[0];
    expect(document.activeElement).not.toBe(document.body);
    expect(screen.getByRole("navigation").contains(document.activeElement)).toBe(true);
    expect(firstNavLink).toBeInTheDocument();
  });

  it("toggling the button twice closes the navigation again", async () => {
    const user = userEvent.setup();
    renderShell();

    const toggle = screen.getByTestId("mobile-nav-toggle");
    await user.click(toggle);
    await user.click(toggle);

    expect(screen.getByRole("navigation").closest("aside")).toHaveAttribute("data-open", "false");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("offers a skip link as the first focusable element, targeting the main region", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.tab();

    const skipLink = screen.getByRole("link", { name: "Skip to main content" });
    expect(skipLink).toHaveFocus();

    const main = screen.getByTestId("shell-main");
    expect(skipLink.getAttribute("href")).toBe(`#${main.id}`);
    // The target must be focusable for the jump to actually move focus.
    expect(main).toHaveAttribute("tabIndex", "-1");
  });

  it("names the sidebar landmark so it is distinguishable from other navigation", () => {
    renderShell();
    expect(screen.getByRole("complementary", { name: "Main" })).toBeInTheDocument();
  });

  it("hides the decorative scrim from assistive technology", async () => {
    const user = userEvent.setup();
    const { container } = renderShell();

    await user.click(screen.getByTestId("mobile-nav-toggle"));

    const scrim = container.querySelector('[aria-hidden="true"][class*="scrim"]');
    expect(scrim).not.toBeNull();
    // It is a pointer convenience only -- it must not become a tab stop
    // with no meaningful name.
    expect(scrim).not.toHaveAttribute("tabindex");
  });
});
