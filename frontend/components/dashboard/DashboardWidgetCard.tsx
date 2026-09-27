"use client";

// Shared widget chrome for the dashboard grid (mockup layout parity:
// design/dashboard-design-mockup/). One bordered card, an eyebrow+title
// header with an optional link to the real screen the widget summarizes,
// and a content slot -- every grid widget (Appointments, Attention,
// Pipeline, Recent activity) renders through this instead of repeating
// the same header markup four times. Purely presentational: no data
// fetching, no business logic.
import { useId } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/Card";
import styles from "./DashboardWidgetCard.module.css";

export function DashboardWidgetCard({
  eyebrow,
  title,
  linkHref,
  linkLabel,
  wide = false,
  children,
}: {
  eyebrow: string;
  title: string;
  linkHref?: string;
  linkLabel?: string;
  /** Spans both columns of the desktop grid -- matches the mockup's
   * pipeline widget, which is visually wider than a single-column
   * summary list. Has no effect on the single-column mobile layout. */
  wide?: boolean;
  children: React.ReactNode;
}) {
  const headingId = useId();

  return (
    <section aria-labelledby={headingId} className={[styles.section, wide ? styles.wide : ""].join(" ").trim()}>
      <Card className={styles.card}>
        <header className={styles.header}>
          <div className={styles.titleGroup}>
            <span className={styles.eyebrow}>{eyebrow}</span>
            <h2 id={headingId} className={styles.title}>
              {title}
            </h2>
          </div>
          {linkHref && linkLabel ? (
            <Link href={linkHref} className={styles.link}>
              {linkLabel}
            </Link>
          ) : null}
        </header>
        <div className={styles.body}>{children}</div>
      </Card>
    </section>
  );
}
