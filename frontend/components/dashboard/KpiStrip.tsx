"use client";

// Dashboard KPI strip (dashboard-design integration, visual reference:
// design/dashboard-design-mockup/). Every value comes from
// `lib/dashboard/commandCenter.ts::loadDashboardKpis()` -- this component
// only formats and lays out what that layer returns; it never composes
// API calls itself (docs/ARCHITECTURE.md's data-layer separation). A KPI
// this tenant has no data for yet renders "—", the same convention
// `lib/crm/money.ts::formatMoney()` already uses for a missing amount --
// never a fabricated number.
import { loadDashboardKpis } from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import styles from "./KpiStrip.module.css";

function formatMoneyDecimal(decimal: number | null, currency: string | null): string {
  if (decimal === null || !currency) return "—";
  return `${decimal.toFixed(2)} ${currency}`;
}

function KpiTile({ label, value }: { label: string; value: string }) {
  return (
    <Card className={styles.tile}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
    </Card>
  );
}

export function KpiStrip({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => loadDashboardKpis(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label="Kerncijfers laden…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const kpis = query.data;

  return (
    <div className={styles.strip} data-testid="kpi-strip">
      <KpiTile
        label="Open kansen"
        value={kpis.openOpportunities === null ? "—" : String(kpis.openOpportunities)}
      />
      <KpiTile
        label="Waarde in pijplijn"
        value={formatMoneyDecimal(kpis.pipelineValueDecimal, kpis.pipelineCurrency)}
      />
      <KpiTile label="Afspraken vandaag" value={String(kpis.appointmentsToday)} />
      <KpiTile label="Ongelezen gesprekken" value={String(kpis.unreadConversations)} />
    </div>
  );
}
