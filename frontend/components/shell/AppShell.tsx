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
//     inside the nav rather than back at the top of the document.
// Each is scoped to the overlay case; at desktop width the sidebar is
// static, always visible, and none of this applies.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Navigation } from "./Navigation";
import { TopBar } from "./TopBar";
import styles from "./AppShell.module.css";

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
      if (event.key === "Escape") closeMobileNav();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [mobileNavOpen, closeMobileNav]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    // Move focus to the first link in the now-visible overlay. This is
    // not a focus *trap*: the sidebar is still part of the page, and the
    // roadmap's own "no new modal framework" rule applies -- Escape and
    // the toggle are the documented ways out.
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
        <main className={styles.main} id={mainId} tabIndex={-1} data-testid="shell-main">
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
        <div className={styles.sidebarBrand}>Product</div>
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
        <main className={styles.main} id={mainId} tabIndex={-1} data-testid="shell-main">
          {children}
        </main>
      </div>
    </div>
  );
}
