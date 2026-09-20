// A form/section-scoped feedback banner -- for mutation results
// ("Delegation created: id=…", "Failed: …") that belong next to the
// control that triggered them, not a full-page ErrorState/EmptyState
// (StatePanel-based, components/ui/states.tsx), which is for "this
// whole section has nothing/failed to load" instead.
import styles from "./InlineNotice.module.css";

export type NoticeTone = "neutral" | "success" | "warning" | "danger";

export function InlineNotice({
  tone = "neutral",
  children,
  onDismiss,
}: {
  tone?: NoticeTone;
  children: React.ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div
      className={styles.notice}
      data-tone={tone}
      role={tone === "danger" ? "alert" : "status"}
    >
      <div className={styles.body}>{children}</div>
      {onDismiss ? (
        <button
          type="button"
          className={styles.dismiss}
          onClick={onDismiss}
          aria-label="Dismiss"
        >
          ×
        </button>
      ) : null}
    </div>
  );
}
