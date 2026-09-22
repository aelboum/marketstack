// Thin, replaceable dashboard layout (dashboard-design integration).
// Purely presentational -- no data, no business logic -- so the column
// count/arrangement can change later (docs/ROADMAP.md's own "2 columns
// -> 3 columns without rewriting the business widgets" requirement)
// without touching any widget. Responsive via CSS Grid `auto-fit` only:
// no ResizeObserver, no JS breakpoint math, matching the product's
// existing CSS-only responsive convention (see app/design-system.test.ts's
// breakpoint policy).
import styles from "./DashboardGrid.module.css";

export function DashboardGrid({ children }: { children: React.ReactNode }) {
  return <div className={styles.grid}>{children}</div>;
}
