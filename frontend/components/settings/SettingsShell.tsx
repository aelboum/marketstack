"use client";

// The replaceable *settings* shell -- the same idea UI-1's `AppShell`
// established for the application, applied one level down.
//
// `variant` selects between a settings sidebar and settings tabs.
// `SettingsNavigation`, and every settings page underneath, are
// unaffected by which one is active: only this file's own JSX and its
// CSS module change, and children always render into the same
// `data-testid="settings-main"` node in both variants (see
// SettingsShell.test.tsx, which asserts exactly that).
//
// A settings page therefore never owns: the sidebar-vs-tabs decision,
// the navigation grouping, the sidebar width, the container width, or
// the responsive arrangement. Those are shell decisions, and all of them
// live in SettingsShell.module.css.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SETTINGS_AREAS, settingsHref, type SettingsArea } from "@/lib/settings/config";
import { Badge } from "@/components/ui/Badge";
import styles from "./SettingsShell.module.css";

export type SettingsLayout = "sidebar" | "tabs";

function isActive(pathname: string, href: string, area: SettingsArea): boolean {
  // The index area ("General") must not match every deeper settings
  // route the way a segment-bearing area legitimately does.
  if (!area.segment) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SettingsNavigation({
  tenantId,
  areas = SETTINGS_AREAS,
}: {
  tenantId: string;
  areas?: SettingsArea[];
}) {
  const pathname = usePathname();

  return (
    <nav aria-label="Settings sections" className={styles.nav}>
      {areas.map((area) => {
        const href = settingsHref(tenantId, area);
        const active = isActive(pathname, href, area);
        return (
          <Link
            key={area.key}
            href={href}
            className={styles.link}
            data-active={active}
            aria-current={active ? "page" : undefined}
          >
            {area.label}
            {/* Status is carried by a text badge, never by color alone. */}
            {area.status === "unavailable" ? <Badge tone="neutral">Not available</Badge> : null}
          </Link>
        );
      })}
    </nav>
  );
}

export function SettingsShell({
  tenantId,
  variant = "sidebar",
  areas,
  children,
}: {
  tenantId: string;
  variant?: SettingsLayout;
  areas?: SettingsArea[];
  children: React.ReactNode;
}) {
  return (
    <div className={styles.shell} data-settings-layout={variant} data-testid="settings-shell">
      <SettingsNavigation tenantId={tenantId} areas={areas} />
      <div className={styles.main} data-testid="settings-main">
        {children}
      </div>
    </div>
  );
}

/** A titled block inside a settings page. Owns the heading semantics
 * (always a real `<h2>` with the section's own accessible name) so pages
 * do not each re-invent them, and so a later typography change is one
 * edit in the CSS module. */
export function SettingsSection({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const headingId = `settings-section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <div className={styles.sectionHeader}>
        <div>
          <h2 id={headingId} className={styles.sectionTitle}>
            {title}
          </h2>
          {description ? <p className={styles.sectionDescription}>{description}</p> : null}
        </div>
        {actions ? <div>{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}
