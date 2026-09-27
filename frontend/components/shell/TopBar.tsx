"use client";

// Second of the three replaceable shell pieces. In "sidebar" layout this
// renders account/tenant chrome only; in "topnav" layout it also embeds
// the horizontal Navigation, per AppShell's `layout` prop -- Navigation
// itself does not know or care which arrangement it is in.

import type { RefObject } from "react";
import Link from "next/link";
import { Menu } from "@/components/ui/Menu";
import { useLocale, useTranslate, type Locale } from "@/lib/i18n/locale-context";
import { Navigation } from "./Navigation";
import styles from "./TopBar.module.css";

const LOCALES: Locale[] = ["NL", "EN"];

/** Visual only -- the mockup's own header search box, approved as a
 * cosmetic element (design/dashboard-design-mockup/). No search index,
 * no keyboard-shortcut handler, no results: a real search feature was
 * explicitly out of scope for the dashboard layout work this came from. */
function HeaderSearch() {
  const t = useTranslate();
  return (
    <label className={styles.search}>
      <span className="visually-hidden">{t("Zoeken", "Search")}</span>
      <input
        className={styles.searchInput}
        type="text"
        disabled
        placeholder={t("Zoek klanten, deals, berichten", "Search customers, deals, messages")}
      />
      <span className={styles.searchKbd} aria-hidden="true">
        ⌘K
      </span>
    </label>
  );
}

function LanguageToggle() {
  const { locale, setLocale } = useLocale();
  return (
    <div className={styles.langGroup} role="group" aria-label="Language">
      {LOCALES.map((code) => (
        <button
          key={code}
          type="button"
          className={styles.langButton}
          data-active={code === locale}
          aria-pressed={code === locale}
          onClick={() => setLocale(code)}
        >
          {code}
        </button>
      ))}
    </div>
  );
}

export function TopBar({
  tenantId,
  userId,
  onLogout,
  showEmbeddedNav,
  onMenuButtonClick,
  navOpen = false,
  navControlsId,
  menuButtonRef,
}: {
  tenantId: string;
  userId: string;
  onLogout: () => void;
  showEmbeddedNav: boolean;
  onMenuButtonClick: () => void;
  /** Whether the navigation this button controls is currently open --
   * announced via aria-expanded so the state is not sighted-only. */
  navOpen?: boolean;
  navControlsId?: string;
  menuButtonRef?: RefObject<HTMLButtonElement | null>;
}) {
  const initials = userId.slice(0, 2).toUpperCase();

  return (
    <header className={styles.bar}>
      <div className={styles.start}>
        <button
          type="button"
          ref={menuButtonRef}
          className={styles.menuButton}
          aria-label={navOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={navOpen}
          aria-controls={navControlsId}
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

      <HeaderSearch />

      <div className={styles.end}>
        <LanguageToggle />
        {/* The workspace this session is acting in. The label is part of
            the text rather than a `title` tooltip, which is neither
            keyboard-reachable nor announced reliably; the full id stays
            available to assistive tech even when CSS truncates it
            visually on a narrow screen. */}
        <span className={styles.tenantTag}>
          <span className={styles.tenantLabel}>Workspace</span>
          <span className={styles.tenantValue}>{tenantId}</span>
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
