"use client";

// One of the three replaceable shell pieces (AppShell/Navigation/TopBar +
// MainContent, per docs/ARCHITECTURE.md §6.1's shell diagram). Domain
// pages never import this directly -- only AppShell does -- so changing
// navigation grouping, orientation, or which items exist is a change
// here and in lib/nav/config.ts only.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS } from "@/lib/nav/config";
import { Badge } from "@/components/ui/Badge";
import styles from "./Navigation.module.css";

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
        {NAV_ITEMS.map((item) => {
          if (item.status === "planned" || !item.segment) {
            return (
              <li key={item.key}>
                <span className={styles.disabled} aria-disabled="true">
                  {item.label}
                  <Badge tone="neutral">
                    <span className={styles.plannedBadge}>Coming soon</span>
                  </Badge>
                </span>
              </li>
            );
          }

          const href = `/t/${tenantId}/${item.segment}`;
          const isActive = pathname === href || pathname.startsWith(`${href}/`);

          return (
            <li key={item.key}>
              <Link href={href} className={styles.link} data-active={isActive}>
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
