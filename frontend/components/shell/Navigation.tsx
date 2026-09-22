"use client";

// One of the three replaceable shell pieces (AppShell/Navigation/TopBar +
// MainContent, per docs/ARCHITECTURE.md §6.1's shell diagram). Domain
// pages never import this directly -- only AppShell does -- so changing
// navigation grouping, orientation, or which items exist is a change
// here and in lib/nav/config.ts only.
//
// Renders `NAV_ITEMS` (docs/ROADMAP.md Phase 28 + the later navigation
// correction pass: the approved, mockup-matching 11-item IA) rather than
// a flat list of every technical module. An item's `children` render as
// an always-visible nested list beneath it -- the same shape the older
// grouped nav used, just driven by one flat `NavItem[]` instead of a
// separate `NavGroup[]`.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, type NavItem } from "@/lib/nav/config";
import { Badge } from "@/components/ui/Badge";
import { useLocale } from "@/lib/i18n/locale-context";
import styles from "./Navigation.module.css";

function pickLabel(item: NavItem, locale: "NL" | "EN"): string {
  return locale === "EN" ? (item.labelEn ?? item.label) : item.label;
}

/** Whether at least one child is itself a real, available destination --
 * this is what decides whether a parent with no route of its own
 * (Groei, Beheer) renders as a real organizational heading with its
 * children listed, or (Boekhouding, whose one child is also still
 * planned) collapses into a single disabled "Coming soon" entry instead
 * of a disabled parent above an equally disabled child. */
function hasAvailableChild(item: NavItem): boolean {
  return (item.children ?? []).some((child) => child.segment && child.status === "available");
}

function NavEntry({
  tenantId,
  item,
  pathname,
  label,
}: {
  tenantId: string;
  item: NavItem;
  pathname: string;
  label: string;
}) {
  if (!item.segment && hasAvailableChild(item)) {
    // Pure organizational heading (Groei, Beheer) -- not a destination
    // itself, but not "not yet built" either: real destinations exist
    // beneath it, listed as its children.
    return <span className={styles.groupLabel}>{label}</span>;
  }

  if (item.status === "planned" || !item.segment) {
    return (
      <span className={styles.disabled} aria-disabled="true">
        {label}
        <Badge tone="neutral">
          <span className={styles.plannedBadge}>Coming soon</span>
        </Badge>
      </span>
    );
  }

  const href = `/t/${tenantId}/${item.segment}`;
  const isActive = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      className={styles.link}
      data-active={isActive}
      // `data-active` styles it; `aria-current` is what tells a
      // screen-reader user which item is the current page -- without it
      // the active state is sighted-only.
      aria-current={isActive ? "page" : undefined}
    >
      {label}
    </Link>
  );
}

export function Navigation({
  tenantId,
  orientation = "vertical",
}: {
  tenantId: string;
  orientation?: "vertical" | "horizontal";
}) {
  const pathname = usePathname();
  const { locale } = useLocale();

  return (
    <nav aria-label="Product navigation">
      <ul className={styles.list} data-orientation={orientation}>
        {NAV_ITEMS.map((item) => {
          const label = pickLabel(item, locale);
          // Children render beneath a real link (Inbox -> Telefonie)
          // unconditionally, or beneath a parent-only heading (Groei,
          // Beheer) that has at least one available child -- never
          // beneath a parent that itself collapsed into a single
          // disabled "Coming soon" entry (Boekhouding), which would
          // otherwise show a disabled child under an equally disabled
          // parent for no benefit.
          const showChildren = !!item.children?.length && (!!item.segment || hasAvailableChild(item));

          return (
            <li key={item.key} className={showChildren ? styles.group : undefined}>
              <NavEntry tenantId={tenantId} item={item} pathname={pathname} label={label} />
              {showChildren ? (
                <ul className={styles.groupList}>
                  {item.children!.map((child) => (
                    <li key={child.key}>
                      <NavEntry
                        tenantId={tenantId}
                        item={child}
                        pathname={pathname}
                        label={pickLabel(child, locale)}
                      />
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
