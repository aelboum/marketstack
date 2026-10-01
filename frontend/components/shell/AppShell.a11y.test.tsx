import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppShell } from "./AppShell";

// UI-8: the shell's narrow-screen and keyboard behavior. Kept in its own
// file so the UI-1 AppShell.test.tsx contract (layout replaceability)
// stays focused on what it was written to prove.

// Mutable so a test can simulate a client-side route change under the
// persistent shell (rerender with a new pathname).
const navigation = vi.hoisted(() => ({ pathname: "/t/tenant-1/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
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
  useTranslate: () => (nl: string) => nl,
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

// A controllable `matchMedia` for the one query the shell listens to.
// jsdom ships none, so the shell treats its absence as "no resize
// signal"; these tests install one to drive the breakpoint crossing.
function installMatchMedia() {
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  const original = window.matchMedia;
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
      listeners.add(listener),
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
      listeners.delete(listener),
  }));
  return {
    crossTo(matches: boolean) {
      act(() => {
        for (const listener of listeners) listener({ matches } as MediaQueryListEvent);
      });
    },
    restore() {
      window.matchMedia = original;
    },
  };
}

describe("AppShell mobile navigation state (UI-8 F1/F2)", () => {
  afterEach(() => {
    navigation.pathname = "/t/tenant-1/dashboard";
  });

  it.each(["sidebar", "topnav"] as const)(
    "closes the %s overlay after a route change and moves focus to the new page",
    async (layout) => {
      const user = userEvent.setup();
      // A fresh element per render: the mocked `usePathname` is not a
      // subscription, so an identical element would let React bail out.
      const shell = () => (
        <AppShell layout={layout} tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
          <div data-testid="domain-page">page</div>
        </AppShell>
      );
      const { rerender } = render(shell());

      const toggle = screen.getByTestId("mobile-nav-toggle");
      await user.click(toggle);
      expect(toggle).toHaveAttribute("aria-expanded", "true");

      navigation.pathname = "/t/tenant-1/crm";
      rerender(shell());

      expect(toggle).toHaveAttribute("aria-expanded", "false");
      expect(screen.getByTestId("shell-main")).toHaveFocus();
      const overlay = document.getElementById(toggle.getAttribute("aria-controls") as string);
      if (layout === "topnav") expect(overlay).toBeNull();
      else expect(overlay).toHaveAttribute("data-open", "false");
    },
  );

  it("does not move focus on a route change while the overlay is closed", () => {
    const shell = () => (
      <AppShell layout="sidebar" tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
        <input aria-label="page field" />
      </AppShell>
    );
    const { rerender } = render(shell());
    const field = screen.getByLabelText("page field");
    field.focus();

    navigation.pathname = "/t/tenant-1/crm";
    rerender(shell());

    expect(field).toHaveFocus();
  });

  it.each(["sidebar", "topnav"] as const)(
    "closes the %s overlay when the viewport crosses to desktop width",
    async (layout) => {
      const media = installMatchMedia();
      try {
        const user = userEvent.setup();
        render(
          <AppShell layout={layout} tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
            <div data-testid="domain-page">page</div>
          </AppShell>,
        );

        const toggle = screen.getByTestId("mobile-nav-toggle");
        await user.click(toggle);
        expect(toggle).toHaveAttribute("aria-expanded", "true");

        // Narrowing again must not close it; only the desktop crossing does.
        media.crossTo(false);
        expect(toggle).toHaveAttribute("aria-expanded", "true");

        media.crossTo(true);
        expect(toggle).toHaveAttribute("aria-expanded", "false");
        // Topnav at desktop width must not keep a second, vertical nav.
        if (layout === "topnav") expect(screen.getAllByRole("navigation")).toHaveLength(1);
      } finally {
        media.restore();
      }
    },
  );
});

describe("AppShell drawer focus cycle (UI-8 F3)", () => {
  function renderLayout(layout: "sidebar" | "topnav") {
    render(
      <AppShell layout={layout} tenantId="tenant-1" userId="user-1" onLogout={vi.fn()}>
        <button type="button">page action</button>
      </AppShell>,
    );
    return screen.getByTestId("mobile-nav-toggle");
  }

  function drawerFocusables(toggle: HTMLElement) {
    const drawer = document.getElementById(toggle.getAttribute("aria-controls") as string);
    expect(drawer).not.toBeNull();
    const nodes = Array.from(
      (drawer as HTMLElement).querySelectorAll<HTMLElement>("a[href], button:not([disabled])"),
    );
    expect(nodes.length).toBeGreaterThan(1);
    return { first: nodes[0], last: nodes[nodes.length - 1] };
  }

  it.each(["sidebar", "topnav"] as const)(
    "%s: Tab from the last drawer item wraps to the toggle",
    async (layout) => {
      const user = userEvent.setup();
      const toggle = renderLayout(layout);
      await user.click(toggle);
      const { last } = drawerFocusables(toggle);

      last.focus();
      await user.tab();

      expect(toggle).toHaveFocus();
    },
  );

  it.each(["sidebar", "topnav"] as const)(
    "%s: Tab from the toggle moves to the first drawer item",
    async (layout) => {
      const user = userEvent.setup();
      const toggle = renderLayout(layout);
      await user.click(toggle);
      const { first } = drawerFocusables(toggle);

      toggle.focus();
      await user.tab();

      expect(first).toHaveFocus();
    },
  );

  it.each(["sidebar", "topnav"] as const)(
    "%s: Shift+Tab from the first drawer item wraps to the toggle",
    async (layout) => {
      const user = userEvent.setup();
      const toggle = renderLayout(layout);
      await user.click(toggle);
      const { first } = drawerFocusables(toggle);

      first.focus();
      await user.tab({ shift: true });

      expect(toggle).toHaveFocus();
    },
  );

  it.each(["sidebar", "topnav"] as const)(
    "%s: Shift+Tab from the toggle moves to the last drawer item",
    async (layout) => {
      const user = userEvent.setup();
      const toggle = renderLayout(layout);
      await user.click(toggle);
      const { last } = drawerFocusables(toggle);

      toggle.focus();
      await user.tab({ shift: true });

      expect(last).toHaveFocus();
    },
  );

  it("leaves the normal Tab order alone while the drawer is closed", async () => {
    const user = userEvent.setup();
    const toggle = renderLayout("sidebar");
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    toggle.focus();
    await user.tab();

    // The next element in document order (the TopBar brand link), not a
    // jump back into the closed drawer.
    expect(screen.getByRole("link", { name: "Product" })).toHaveFocus();
  });

  it("still closes on Escape mid-cycle and returns focus to the toggle", async () => {
    const user = userEvent.setup();
    const toggle = renderLayout("sidebar");
    await user.click(toggle);
    const { last } = drawerFocusables(toggle);

    last.focus();
    await user.tab();
    expect(toggle).toHaveFocus();
    await user.tab();
    await user.keyboard("{Escape}");

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });
});
