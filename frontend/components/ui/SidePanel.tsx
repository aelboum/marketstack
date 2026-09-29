"use client";

// A right-anchored, full-height detail panel (mockup layout parity:
// design/Calendar.dc.html's own `dt-panel` -- clicking an appointment or
// calendar event opens this, not the centered `Dialog`). Shares Dialog's
// focus-trap/Escape/backdrop-click behavior (duplicated rather than
// imported: Dialog.tsx is a widely-used, untested primitive, and this
// component's container shape -- header/scrollable-body/pinned-footer,
// right-anchored, full viewport height -- is different enough that
// forcing one shared component would need a variant prop threading
// through every call site for no real reuse benefit).
import { useEffect, useId, useRef } from "react";
import styles from "./SidePanel.module.css";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function SidePanel({
  open,
  onClose,
  kicker,
  title,
  tag,
  footer,
  children,
  closeLabel = "Sluiten",
}: {
  open: boolean;
  onClose: () => void;
  /** Small label row above the title (mockup: a coloured dot + "Afspraak"
   * / "Evenement"). */
  kicker?: React.ReactNode;
  title: React.ReactNode;
  /** Status pill under the title (appointments only). */
  tag?: React.ReactNode;
  /** Pinned action row at the bottom, outside the scrollable body. */
  footer?: React.ReactNode;
  children?: React.ReactNode;
  closeLabel?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const panelNode = panelRef.current;
    const focusable = panelNode?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    (focusable?.[0] ?? panelNode)?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panelNode) return;

      const focusableNodes = Array.from(
        panelNode.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusableNodes.length === 0) return;
      const first = focusableNodes[0];
      const last = focusableNodes[focusableNodes.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className={styles.overlay}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className={styles.header}>
          <div className={styles.headerText}>
            {kicker ? <div className={styles.kicker}>{kicker}</div> : null}
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            {tag ? <div className={styles.tagRow}>{tag}</div> : null}
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label={closeLabel}
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>
        <div className={styles.body}>{children}</div>
        {footer ? <footer className={styles.footer}>{footer}</footer> : null}
      </div>
    </div>
  );
}
