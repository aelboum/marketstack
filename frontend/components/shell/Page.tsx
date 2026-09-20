import type { HTMLAttributes } from "react";
import styles from "./Page.module.css";

// The container every domain page renders into
// (`<AppShell><Page>...</Page></AppShell>`, per the UI Track roadmap's
// replaceable-shell diagram) instead of hand-rolling its own max-width/
// padding. Changing page container width later is a one-file change
// here, not a per-page edit.
export function Page({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={[styles.page, className].filter(Boolean).join(" ")} {...props} />;
}
