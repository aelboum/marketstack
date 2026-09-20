// Shared visual shape behind every "nothing to render normally" state
// (loading, empty, error, permission-denied). UI-1 scope explicitly asks
// for these to be "reusable rather than separately implemented on every
// page" -- LoadingState/EmptyState/ErrorState/PermissionDeniedState below
// are thin, semantically-named wrappers over this one primitive rather
// than four divergent implementations.
import styles from "./StatePanel.module.css";

export type StateTone = "neutral" | "danger" | "warning";

export type StatePanelProps = {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  tone?: StateTone;
  action?: React.ReactNode;
  secondaryAction?: React.ReactNode;
  /** Tighter padding for use inside a card/list row rather than a full page. */
  inline?: boolean;
  role?: "status" | "alert";
};

export function StatePanel({
  icon,
  title,
  description,
  tone = "neutral",
  action,
  secondaryAction,
  inline = false,
  role,
}: StatePanelProps) {
  return (
    <div className={styles.panel} data-tone={tone} data-inline={inline} role={role}>
      {icon ? (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <p className={styles.title}>{title}</p>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action || secondaryAction ? (
        <div className={styles.actions}>
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </span>
  );
}
