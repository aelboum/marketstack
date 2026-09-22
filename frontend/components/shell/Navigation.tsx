"use client";

// One of the three replaceable shell pieces (AppShell/Navigation/TopBar +
// MainContent, per docs/ARCHITECTURE.md §6.1's shell diagram). Domain
// pages never import this directly -- only AppShell does -- so changing
// navigation grouping, orientation, or which items exist is a change
// here and in lib/nav/config.ts only.
//
// Renders `NAV_GROUPS` (docs/ROADMAP.md Phase 28: business-oriented
// groups, e.g. "Klanten", "Agenda" -- never a raw backend module name as
// the primary label) rather than a flat list of every technical module.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_GROUPS, type NavItem } from "@/lib/nav/config";
import { Badge } from "@/components/ui/Badge";
import styles from "./Navigation.module.css";

function NavEntry({ tenantId, item, pathname }: { tenantId: string; item: NavItem; pathname: string }) {
  if (item.status === "planned" || !item.segment) {
    return (
      <span className={styles.disabled} aria-disabled="true">
        {item.label}
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
      {item.label}
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

  return (
    <nav aria-label="Product navigation">
      <ul className={styles.list} data-orientation={orientation}>
        {NAV_GROUPS.map((group) => {
          // A group whose one item already carries the group's own label
          // (Vandaag, Inbox, Agenda) renders as a single top-level entry
          // -- a separate non-interactive heading above it would just
          // repeat the same word for no reason. A group with more than
          // one item, or whose single item is named differently from the
          // group (Verkoop -> "Verkoop" is actually this shape today,
          // kept general rather than special-cased), gets a real heading.
          const isBareSingleItem =
            group.items.length === 1 && group.items[0].label === group.label;

          if (isBareSingleItem) {
            return (
              <li key={group.key}>
                <NavEntry tenantId={tenantId} item={group.items[0]} pathname={pathname} />
              </li>
            );
          }

          return (
            <li key={group.key} className={styles.group}>
              {/* A heading, not a link -- the group itself has no
                  destination, only its items do. */}
              <span className={styles.groupLabel}>{group.label}</span>
              <ul className={styles.groupList}>
                {group.items.map((item) => (
                  <li key={item.key}>
                    <NavEntry tenantId={tenantId} item={item} pathname={pathname} />
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
