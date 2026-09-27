"use client";

// Shared list-row presentation for the dashboard's list-style widgets
// (mockup layout parity: design/dashboard-design-mockup/). Purely
// presentational -- takes already-loaded, already-real data from its
// caller (AttentionSection, UpcomingAppointmentsSection,
// RecentActivitySection, all unchanged in their own data-fetching) and
// renders one row: a short lead badge, a title/meta pair, an optional
// status tag, and an aside value. Renders as a real `<a>` when `href` is
// given (a real destination exists), or a plain row when it is not --
// never a link to a page that doesn't exist.
import Link from "next/link";
import styles from "./DashboardListRow.module.css";

export type DashboardListRowTone = "neutral" | "info" | "success" | "warning" | "danger";

const TONE_CLASS: Record<DashboardListRowTone, string> = {
  neutral: styles.tagNeutral,
  info: styles.tagInfo,
  success: styles.tagSuccess,
  warning: styles.tagWarning,
  danger: styles.tagDanger,
};

function RowContent({
  lead,
  title,
  meta,
  tag,
  tone = "neutral",
  aside,
}: {
  lead: string;
  title: string;
  meta?: string;
  tag?: string;
  tone?: DashboardListRowTone;
  aside?: string;
}) {
  return (
    <>
      <span className={styles.lead} aria-hidden="true">
        {lead}
      </span>
      <span className={styles.textGroup}>
        <span className={styles.title}>{title}</span>
        {meta ? <span className={styles.meta}>{meta}</span> : null}
      </span>
      {tag ? <span className={`${styles.tag} ${TONE_CLASS[tone]}`}>{tag}</span> : null}
      {aside ? <span className={styles.aside}>{aside}</span> : null}
    </>
  );
}

export function DashboardListRow(
  props: {
    lead: string;
    title: string;
    meta?: string;
    tag?: string;
    tone?: DashboardListRowTone;
    aside?: string;
  } & ({ href: string } | { href?: undefined }),
) {
  if ("href" in props && props.href) {
    return (
      <Link href={props.href} className={styles.row}>
        <RowContent {...props} />
      </Link>
    );
  }
  return (
    <div className={styles.row} data-static="true">
      <RowContent {...props} />
    </div>
  );
}
