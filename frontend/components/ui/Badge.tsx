import styles from "./Badge.module.css";

export type BadgeProps = {
  children: React.ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
};

export function Badge({ children, tone = "neutral" }: BadgeProps) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}
