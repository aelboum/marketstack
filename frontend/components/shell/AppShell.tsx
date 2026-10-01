"use client";

// The replaceable application shell (docs/ARCHITECTURE.md §6.1 /
// docs/ROADMAP.md UI Track). `layout` selects between a sidebar
// arrangement and a top-nav arrangement -- Navigation, TopBar, and every
// domain page underneath are unaffected by which one is active; only
// this file's own JSX/CSS changes. `children` (a domain page, always
// wrapped in <Page> by the page itself) always renders into the same
// `data-testid="shell-main"` node, in both layouts -- that is the
// concrete, testable form of "replaceable without rewriting domain
// pages" (see AppShell.test.tsx).
//
// UI-8 hardened the narrow-screen behavior of the sidebar arrangement
// without changing that architecture. Below the mobile breakpoint the
// sidebar is an overlay, which means it needs the three things any
// overlay needs and previously lacked:
//   - it must leave the tab order and the accessibility tree while
//     closed (it was only translated off-screen, so keyboard users
//     tabbed through every invisible nav link before reaching the page,
//     and screen readers announced all of them). That is enforced in
//     CSS via `visibility`, which removes an element from both;
//   - Escape must close it, and focus must return to the control that
//     opened it;
//   - opening it must move focus into it, so the next Tab continues
//     inside the nav rather than back at the top of the document; while
//     open, Tab cycles between the toggle and the nav instead of moving
//     onto controls hidden underneath the drawer.
// Each is scoped to the overlay case; at desktop width the sidebar is
// static, always visible, and none of this applies.
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Navigation } from "./Navigation";
import { TopBar } from "./TopBar";
import styles from "./AppShell.module.css";

// Same selector as components/ui/Dialog.tsx and SidePanel.tsx.
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export type ShellLayout = "sidebar" | "topnav";

export function AppShell({
  layout = "sidebar",
  tenantId,
  userId,
  onLogout,
  children,
}: {
  layout?: ShellLayout;
  tenantId: string;
  userId: string;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const sidebarId = useId();
  const mainId = useId();

  const closeMobileNav = useCallback(() => {
    setMobileNavOpen(false);
    // Returning focus to the toggle is what makes the overlay
    // keyboard-reversible: without it, focus would fall back to
    // <body> and the next Tab would restart at the top of the page.
    toggleRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!mobileNavOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        closeMobileNav();
        return;
      }
      if (event.key !== "Tab") return;

      // Keep Tab cycling between the toggle and the drawer's own links
      // while it is open. Without this, Tab leaves the drawer for TopBar
      // controls and page content that sit underneath it, fully hidden
      // (WCAG 2.2 SC 2.4.11). The toggle stays in the cycle because it is
      // the visible way back out; this is not a modal (no aria-modal, the
      // pointer still reaches the page), just a bounded Tab order. Same
      // first/last wrap as Dialog.tsx, with the toggle as the hinge.
      const toggle = toggleRef.current;
      const drawer = sidebarRef.current;
      if (!toggle || !drawer) return;
      const focusableNodes = Array.from(drawer.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusableNodes.length === 0) return;
      const first = focusableNodes[0];
      const last = focusableNodes[focusableNodes.length - 1];
      const active = document.activeElement;

      if (active === toggle) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if ((event.shiftKey && active === first) || (!event.shiftKey && active === last)) {
        event.preventDefault();
        toggle.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [mobileNavOpen, closeMobileNav]);

  // The shell persists across route changes (it lives in the tenant
  // layout), so following a link from the open overlay would otherwise
  // load the new page behind a still-open drawer and scrim. Focus goes
  // to the new page's main region, not back to the toggle: the user has
  // chosen a destination, and that is where the next Tab should start.
  const pathname = usePathname();
  const lastPathnameRef = useRef(pathname);
  useEffect(() => {
    if (lastPathnameRef.current === pathname) return;
    lastPathnameRef.current = pathname;
    if (!mobileNavOpen) return;
    setMobileNavOpen(false);
    mainRef.current?.focus();
  }, [pathname, mobileNavOpen]);

  // The overlay only exists below the mobile breakpoint. Crossing to
  // desktop width while it is open would leave stale open state behind:
  // in topnav a second, in-flow vertical nav next to the horizontal one
  // (with the toggle CSS-hidden, so no visible way to close it); in
  // sidebar a drawer that silently reopens on the next shrink. Same
  // breakpoint as AppShell.module.css / TopBar.module.css.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const wide = window.matchMedia("(min-width: 48rem)");
    function handleChange(event: MediaQueryListEvent) {
      if (event.matches) setMobileNavOpen(false);
    }
    wide.addEventListener("change", handleChange);
    return () => wide.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (!mobileNavOpen) return;
    // Move focus to the first link in the now-visible overlay. This is
    // not a modal focus *trap*: the sidebar is still part of the page,
    // and the roadmap's own "no new modal framework" rule applies --
    // Escape and the toggle (kept in the Tab cycle above) are the
    // documented ways out.
    const firstLink = sidebarRef.current?.querySelector<HTMLElement>("a[href], button");
    firstLink?.focus();
  }, [mobileNavOpen]);

  if (layout === "topnav") {
    return (
      <div className={styles.shell} data-layout="topnav" data-testid="app-shell">
        <a className={styles.skipLink} href={`#${mainId}`}>
          Skip to main content
        </a>
        <TopBar
          tenantId={tenantId}
          userId={userId}
          onLogout={onLogout}
          showEmbeddedNav
          onMenuButtonClick={() => setMobileNavOpen((value) => !value)}
          navOpen={mobileNavOpen}
          navControlsId={sidebarId}
          menuButtonRef={toggleRef}
        />
        {/* `centerNav`'s horizontal Navigation is CSS-hidden below the
            mobile breakpoint (TopBar.module.css), which is what the
            toggle above actually needs to open onto -- previously it
            controlled an id that did not exist anywhere in this layout,
            so the button was inert and its `aria-controls` pointed at
            nothing. Mounted only while open, so desktop topnav (which
            already has the horizontal nav) never carries this in the DOM. */}
        {mobileNavOpen ? (
          <>
            <div className={styles.scrim} aria-hidden="true" onClick={closeMobileNav} />
            <aside
              ref={sidebarRef}
              id={sidebarId}
              className={styles.sidebar}
              data-open={mobileNavOpen}
              aria-label="Main"
            >
              <Navigation tenantId={tenantId} orientation="vertical" />
            </aside>
          </>
        ) : null}
        <main ref={mainRef} className={styles.main} id={mainId} tabIndex={-1} data-testid="shell-main">
          {children}
        </main>
      </div>
    );
  }

  return (
    <div className={styles.shell} data-layout="sidebar" data-testid="app-shell">
      {/* First focusable element on the page: lets a keyboard user jump
          past the whole navigation instead of tabbing through it on
          every route. Visually hidden until focused (see the CSS). */}
      <a className={styles.skipLink} href={`#${mainId}`}>
        Skip to main content
      </a>
      {mobileNavOpen ? (
        // Pointer-only convenience. Deliberately not a button and hidden
        // from assistive tech: adding it to the tab order would create a
        // stop with no meaningful name, and Escape already closes.
        <div className={styles.scrim} aria-hidden="true" onClick={closeMobileNav} />
      ) : null}
      <aside
        ref={sidebarRef}
        id={sidebarId}
        className={styles.sidebar}
        data-open={mobileNavOpen}
        aria-label="Main"
      >
        <div className={styles.sidebarBrand}>
          <span className={styles.sidebarBrandMark} aria-hidden="true">
            P
          </span>
          Product
        </div>
        <Navigation tenantId={tenantId} orientation="vertical" />
      </aside>
      <div className={styles.body}>
        <TopBar
          tenantId={tenantId}
          userId={userId}
          onLogout={onLogout}
          showEmbeddedNav={false}
          onMenuButtonClick={() => (mobileNavOpen ? closeMobileNav() : setMobileNavOpen(true))}
          navOpen={mobileNavOpen}
          navControlsId={sidebarId}
          menuButtonRef={toggleRef}
        />
        <main ref={mainRef} className={styles.main} id={mainId} tabIndex={-1} data-testid="shell-main">
          {children}
        </main>
      </div>
    </div>
  );
}
