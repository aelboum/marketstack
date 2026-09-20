"use client";

// Second of the three replaceable shell pieces. In "sidebar" layout this
// renders account/tenant chrome only; in "topnav" layout it also embeds
// the horizontal Navigation, per AppShell's `layout` prop -- Navigation
// itself does not know or care which arrangement it is in.

import Link from "next/link";
import { Menu } from "@/components/ui/Menu";
import { Navigation } from "./Navigation";
import styles from "./TopBar.module.css";

export function TopBar({
  tenantId,
  userId,
  onLogout,
  showEmbeddedNav,
  onMenuButtonClick,
}: {
  tenantId: string;
  userId: string;
  onLogout: () => void;
  showEmbeddedNav: boolean;
  onMenuButtonClick: () => void;
}) {
  const initials = userId.slice(0, 2).toUpperCase();

  return (
    <header className={styles.bar}>
      <div className={styles.start}>
        <button
          type="button"
          className={styles.menuButton}
          aria-label="Toggle navigation"
          data-testid="mobile-nav-toggle"
          onClick={onMenuButtonClick}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <Link href={`/t/${tenantId}/dashboard`} className={styles.brand}>
          Product
        </Link>
      </div>

      {showEmbeddedNav ? (
        <div className={styles.centerNav}>
          <Navigation tenantId={tenantId} orientation="horizontal" />
        </div>
      ) : null}

      <div className={styles.end}>
        <span className={styles.tenantTag} title={tenantId}>
          Tenant: {tenantId}
        </span>
        <Menu
          trigger={
            <span className={styles.accountTrigger}>
              <span className={styles.avatar} aria-hidden="true">
                {initials}
              </span>
              <span className="visually-hidden">Account menu</span>
            </span>
          }
          items={[{ key: "logout", label: "Log out", onSelect: onLogout }]}
        />
      </div>
    </header>
  );
}
