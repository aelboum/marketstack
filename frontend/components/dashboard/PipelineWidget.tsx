"use client";

// Dashboard pipeline widget (mockup layout parity: design/dashboard-
// design-mockup/). Reuses the real CRM pipeline/stage/opportunity data
// via `lib/dashboard/commandCenter.ts::loadPipelineSummary()` -- no
// second pipeline domain model, no new pipeline semantics; this is the
// same `product/crm/pipelines.py` data `components/crm/PipelinesPanel.tsx`
// and `components/crm/OpportunitiesList.tsx` already read, presented as
// a compact per-stage summary (stacked bar + table) instead of two
// separate management screens.
import {
  loadPipelineSummary,
  type PipelineStageSummary,
} from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useTranslate } from "@/lib/i18n/locale-context";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import styles from "./PipelineWidget.module.css";

/** Cycles through existing semantic color tokens only -- never a new
 * hardcoded hex/oklch value -- so each stage gets a visually distinct
 * dot/bar segment regardless of how many stages a tenant has configured. */
const STAGE_TONES = [
  "var(--color-accent)",
  "var(--color-success)",
  "var(--color-warning)",
  "var(--color-text-faint)",
  "var(--color-danger)",
];

function stageTone(index: number): string {
  return STAGE_TONES[index % STAGE_TONES.length];
}

function formatStageValue(stage: PipelineStageSummary, currency: string | null): string {
  if (stage.valueDecimal === null || !currency) return "—";
  return `${stage.valueDecimal.toFixed(2)} ${currency}`;
}

export function PipelineWidget({ tenantId }: { tenantId: string }) {
  const t = useTranslate();
  const query = useApiQuery(() => loadPipelineSummary(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label={t("Pijplijn laden…", "Loading pipeline…")} />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const summary = query.data;

  if (!summary || summary.stages.length === 0) {
    return (
      <EmptyState
        title={t("Nog geen pijplijn", "No pipeline yet")}
        description={t(
          "Zodra er een pijplijn met fases is, verschijnt hier een overzicht van uw verkoopkansen.",
          "Once a pipeline with stages exists, an overview of your sales opportunities appears here.",
        )}
      />
    );
  }

  const toneByStageId = new Map(summary.stages.map((stage, index) => [stage.stageId, stageTone(index)]));

  const columns: DataTableColumn<PipelineStageSummary>[] = [
    {
      key: "stage",
      header: t("Fase", "Stage"),
      render: (stage) => (
        <span className={styles.stageCell}>
          <span
            className={styles.stageDot}
            aria-hidden="true"
            style={{ background: toneByStageId.get(stage.stageId) }}
          />
          {stage.stageName}
        </span>
      ),
    },
    { key: "deals", header: "Deals", render: (stage) => String(stage.dealCount) },
    { key: "value", header: t("Waarde", "Value"), render: (stage) => formatStageValue(stage, summary.currency) },
  ];

  return (
    <div data-testid="pipeline-summary" className={styles.wrapper}>
      <div className={styles.bar} aria-hidden="true">
        {summary.stages.map((stage, index) => (
          <span
            key={stage.stageId}
            className={styles.barSegment}
            style={{ flexGrow: stage.dealCount, background: stageTone(index) }}
          />
        ))}
      </div>
      <DataTable
        columns={columns}
        rows={summary.stages}
        rowKey={(stage) => stage.stageId}
        label={`${t("Pijplijn", "Pipeline")}: ${summary.pipelineName}`}
      />
    </div>
  );
}
