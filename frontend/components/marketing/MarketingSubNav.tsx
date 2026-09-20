"use client";

// Internal Marketing sub-navigation (Campaigns/Forms/Suppressions/
// Templates) -- lives inside the Marketing section only, mirrors
// components/crm/CrmSubNav.tsx. Does not touch lib/nav/config.ts;
// "Marketing" remains one top-level entry there.
import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./MarketingSubNav.module.css";

export function MarketingSubNav({ tenantId }: { tenantId: string }) {
  const pathname = usePathname();
  const items = [
    { key: "campaigns", label: "Campaigns", href: `/t/${tenantId}/marketing/campaigns` },
    { key: "forms", label: "Forms", href: `/t/${tenantId}/marketing/forms` },
    { key: "suppressions", label: "Suppressions", href: `/t/${tenantId}/marketing/suppressions` },
    { key: "templates", label: "Templates", href: `/t/${tenantId}/marketing/templates` },
  ];

  return (
    <nav aria-label="Marketing sections" className={styles.nav}>
      {items.map((item) => (
        <Link
          key={item.key}
          href={item.href}
          className={styles.link}
          data-active={pathname === item.href || pathname.startsWith(`${item.href}/`)}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
