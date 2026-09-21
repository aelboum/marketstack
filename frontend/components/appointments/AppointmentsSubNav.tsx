"use client";

// Internal Appointments sub-navigation -- lives inside the Appointments
// section only, mirrors components/crm/CrmSubNav.tsx and
// components/marketing/MarketingSubNav.tsx. Does not touch
// lib/nav/config.ts; "Appointments" remains one top-level entry there.
//
// The sections are exactly the ones the Phase 7 API can actually serve.
// There is deliberately no "Appointments" tab: the backend exposes no
// authenticated list/detail read for appointments at all (see
// lib/api/appointments.ts's module docstring), so a tab promising a list
// of them would be a fake page.
import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./AppointmentsSubNav.module.css";

export function AppointmentsSubNav({ tenantId }: { tenantId: string }) {
  const pathname = usePathname();
  const base = `/t/${tenantId}/appointments`;
  const items = [
    { key: "calendars", label: "Calendars", href: base },
    { key: "book", label: "Book", href: `${base}/book` },
    { key: "manage", label: "Manage", href: `${base}/manage` },
    { key: "reminders", label: "Reminders", href: `${base}/reminders` },
  ];

  return (
    <nav aria-label="Appointments sections" className={styles.nav}>
      {items.map((item) => (
        <Link
          key={item.key}
          href={item.href}
          className={styles.link}
          // "Calendars" is the section root, so it must not match every
          // deeper route the way the others legitimately do.
          data-active={
            item.key === "calendars"
              ? pathname === item.href || pathname.startsWith(`${item.href}/calendars/`)
              : pathname === item.href || pathname.startsWith(`${item.href}/`)
          }
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
