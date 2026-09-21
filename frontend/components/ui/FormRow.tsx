import type { FormHTMLAttributes, HTMLAttributes } from "react";
import styles from "./FormRow.module.css";

// The one inline-form-row layout this product uses, extracted in UI-9.
//
// It was the same declaration repeated seventeen times across CRM,
// Agency, Conversations, Marketing and Appointments:
//   style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end" }}
// -- and seven of those copies had drifted, omitting `flexWrap: "wrap"`,
// so their controls overflowed on a narrow screen. Extracting it fixes
// those seven and makes the next one correct by default.
//
// This is deliberately a *layout* primitive and nothing more. It renders
// no labels, no error text, no submit handling, and imposes no field
// model: callers keep using <Input>, <label>, <Button> and their own
// `onSubmit` exactly as before, so every existing label, validation
// message, disabled state and accessibility semantic is untouched. A
// form framework is explicitly not in scope.

/** The row as a `<form>` -- the common case, where the row *is* the form. */
export function FormRow({ className, ...props }: FormHTMLAttributes<HTMLFormElement>) {
  return <form className={[styles.row, className].filter(Boolean).join(" ")} {...props} />;
}

/** The same layout as a plain `<div>`, for a row of controls that is not
 * itself a form (or that sits inside a larger one). */
export function FormRowGroup({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={[styles.row, className].filter(Boolean).join(" ")} {...props} />;
}

/** Wraps the control that should absorb the row's spare width. */
export function FormRowGrow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={[styles.grow, className].filter(Boolean).join(" ")} {...props} />;
}
