"use client";

// Internal CRM sub-navigation (Contacts/Companies/Opportunities/
// Pipelines) -- lives inside the CRM section only, distinct from the
// UI-1 shell's own Navigation. Does not touch or duplicate the app-wide
// nav config (lib/nav/config.ts); "CRM" remains one entry there.
import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./CrmSubNav.module.css";

export function CrmSubNav({ tenantId }: { tenantId: string }) {
  const pathname = usePathname();
  const items = [
    { key: "contacts", label: "Contacts", href: `/t/${tenantId}/crm/contacts` },
    { key: "companies", label: "Companies", href: `/t/${tenantId}/crm/companies` },
    { key: "opportunities", label: "Opportunities", href: `/t/${tenantId}/crm/opportunities` },
    { key: "pipelines", label: "Pipelines", href: `/t/${tenantId}/crm/pipelines` },
  ];

  return (
    <nav aria-label="CRM sections" className={styles.nav}>
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
