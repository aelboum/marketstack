"use client";

// Dashboard KPI strip (mockup layout parity: design/dashboard-design-
// mockup/). Every value comes from
// `lib/dashboard/commandCenter.ts::loadDashboardKpis()` -- this component
// only formats and lays out what that layer returns; it never composes
// API calls itself (docs/ARCHITECTURE.md's data-layer separation). A KPI
// this tenant has no data for yet renders "—", the same convention
// `lib/crm/money.ts::formatMoney()` already uses for a missing amount --
// never a fabricated number. Each tile links to the real screen it
// summarizes (matches the mockup: the whole tile is clickable).
import Link from "next/link";
import { loadDashboardKpis } from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useTranslate } from "@/lib/i18n/locale-context";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import styles from "./KpiStrip.module.css";

function formatMoneyDecimal(decimal: number | null, currency: string | null): string {
  if (decimal === null || !currency) return "—";
  return `${decimal.toFixed(2)} ${currency}`;
}

function KpiTile({ href, label, value }: { href: string; label: string; value: string }) {
  return (
    <Link href={href} className={styles.tile}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
    </Link>
  );
}

export function KpiStrip({ tenantId }: { tenantId: string }) {
  const t = useTranslate();
  const query = useApiQuery(() => loadDashboardKpis(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label={t("Kerncijfers laden…", "Loading key figures…")} />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const kpis = query.data;

  return (
    <div className={styles.strip} data-testid="kpi-strip">
      <KpiTile
        href={`/t/${tenantId}/crm/opportunities`}
        label={t("Open kansen", "Open opportunities")}
        value={kpis.openOpportunities === null ? "—" : String(kpis.openOpportunities)}
      />
      <KpiTile
        href={`/t/${tenantId}/crm/opportunities`}
        label={t("Waarde in pijplijn", "Pipeline value")}
        value={formatMoneyDecimal(kpis.pipelineValueDecimal, kpis.pipelineCurrency)}
      />
      <KpiTile
        href={`/t/${tenantId}/appointments`}
        label={t("Afspraken vandaag", "Appointments today")}
        value={String(kpis.appointmentsToday)}
      />
      <KpiTile
        href={`/t/${tenantId}/conversations`}
        label={t("Ongelezen gesprekken", "Unread conversations")}
        value={String(kpis.unreadConversations)}
      />
    </div>
  );
}
