"use client";

// Internal Appointments sub-navigation -- lives inside the Appointments
// section only, mirrors components/crm/CrmSubNav.tsx and
// components/marketing/MarketingSubNav.tsx. Does not touch
// lib/nav/config.ts; "Agenda" remains one top-level entry there.
//
// "Overzicht" (root) is the real week calendar (mockup layout parity:
// design/Calendar.dc.html), backed by `listAppointments()`
// (docs/ROADMAP.md Phase 28 -- the read path this section's own earlier
// comment used to say did not exist. It now does, which is what makes a
// real calendar view possible at all). "Kalenders" (calendar resource
// management: availability rules, booking links) moved off the root to
// make room for it, same real screen, same route depth, just no longer
// the first thing this section shows.
import Link from "next/link";
import { usePathname } from "next/navigation";
import styles from "./AppointmentsSubNav.module.css";

export function AppointmentsSubNav({ tenantId }: { tenantId: string }) {
  const pathname = usePathname();
  const base = `/t/${tenantId}/appointments`;
  const items = [
    { key: "overview", label: "Overzicht", href: base },
    { key: "calendars", label: "Calendars", href: `${base}/calendars` },
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
          // "Overzicht" is the section root, so it must not match every
          // deeper route the way the others legitimately do.
          data-active={
            item.key === "overview"
              ? pathname === item.href
              : pathname === item.href || pathname.startsWith(`${item.href}/`)
          }
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
