"use client";

// Minimal accessible modal dialog -- UI-2's sensitive actions (support
// access approve/deny/revoke, delegation/deny revoke) explicitly need
// "explicit confirmation" (docs/ROADMAP.md UI Track's own UI-2 scope);
// UI-1 shipped Menu but no dialog primitive, so this is added now,
// against the concrete need that surfaced it -- not built speculatively
// ahead of one.
import { useEffect, useId, useRef } from "react";
import { Button } from "./Button";
import styles from "./Dialog.module.css";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  showClose = true,
  closeLabel = "Close dialog",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: React.ReactNode;
  /**
   * Visible close affordance (UI-9). On by default, because a plain
   * `<Dialog>` previously had none at all: dismissing it required
   * knowing to press Escape or to click the backdrop, neither of which
   * is discoverable, and neither of which a touch user is likely to try.
   *
   * `ConfirmDialog` turns it off. A confirmation already renders an
   * explicit, labelled Cancel button, so a second dismiss control would
   * be the duplicate affordance this should not become -- and because
   * that Cancel is the control that carries the pending-state guard,
   * leaving the "×" out is also what keeps a mid-flight confirmation
   * from being dismissed around it.
   */
  showClose?: boolean;
  closeLabel?: string;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!open) return;

    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const dialogNode = dialogRef.current;
    const focusable = dialogNode?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
    (focusable?.[0] ?? dialogNode)?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogNode) return;

      const focusableNodes = Array.from(
        dialogNode.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
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
    <div className={styles.overlay} onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
      >
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {description ? (
          <p id={descriptionId} className={styles.description}>
            {description}
          </p>
        ) : null}
        {children}
        {/* Rendered last in the DOM but positioned top-right by CSS.
            Order matters: the open-effect above focuses the dialog's
            *first* focusable element, so putting the close button first
            would steal initial focus from the form field a user actually
            came to fill in. Positioning it visually without moving it in
            the DOM keeps both behaviors correct. */}
        {showClose ? (
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label={closeLabel}
          >
            <span aria-hidden="true">×</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  pending = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    // `showClose={false}`: the Cancel button below is this dialog's
    // dismiss control, and it is the one that respects `pending`.
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      description={description}
      showClose={false}
    >
      <div className={styles.actions}>
        <Button variant="secondary" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </Button>
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={pending}>
          {pending ? "Working…" : confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}
