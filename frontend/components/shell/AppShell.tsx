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
import { useState } from "react";
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

  if (layout === "topnav") {
    return (
      <div className={styles.shell} data-layout="topnav" data-testid="app-shell">
        <TopBar
          tenantId={tenantId}
          userId={userId}
          onLogout={onLogout}
          showEmbeddedNav
          onMenuButtonClick={() => setMobileNavOpen((value) => !value)}
        />
        <main className={styles.main} data-testid="shell-main">
          {children}
        </main>
      </div>
    );
  }

  return (
    <div className={styles.shell} data-layout="sidebar" data-testid="app-shell">
      {mobileNavOpen ? (
        <div className={styles.scrim} onClick={() => setMobileNavOpen(false)} />
      ) : null}
      <aside className={styles.sidebar} data-open={mobileNavOpen}>
        <div className={styles.sidebarBrand}>Product</div>
        <Navigation tenantId={tenantId} orientation="vertical" />
      </aside>
      <div className={styles.body}>
        <TopBar
          tenantId={tenantId}
          userId={userId}
          onLogout={onLogout}
          showEmbeddedNav={false}
          onMenuButtonClick={() => setMobileNavOpen((value) => !value)}
        />
        <main className={styles.main} data-testid="shell-main">
          {children}
        </main>
      </div>
    </div>
  );
}
