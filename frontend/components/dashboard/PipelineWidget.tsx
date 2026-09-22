"use client";

// Dashboard pipeline widget (dashboard-design integration). Reuses the
// real CRM pipeline/stage/opportunity data via
// `lib/dashboard/commandCenter.ts::loadPipelineSummary()` -- no second
// pipeline domain model, no new pipeline semantics; this is the same
// `product/crm/pipelines.py` data `components/crm/PipelinesPanel.tsx`
// and `components/crm/OpportunitiesList.tsx` already read, presented as
// a compact per-stage summary table instead of two separate management
// screens.
import {
  loadPipelineSummary,
  type PipelineStageSummary,
} from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";

function formatStageValue(stage: PipelineStageSummary, currency: string | null): string {
  if (stage.valueDecimal === null || !currency) return "—";
  return `${stage.valueDecimal.toFixed(2)} ${currency}`;
}

export function PipelineWidget({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => loadPipelineSummary(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label="Pijplijn laden…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const summary = query.data;

  if (!summary || summary.stages.length === 0) {
    return (
      <EmptyState
        title="Nog geen pijplijn"
        description="Zodra er een pijplijn met fases is, verschijnt hier een overzicht van uw verkoopkansen."
      />
    );
  }

  const columns: DataTableColumn<PipelineStageSummary>[] = [
    { key: "stage", header: "Fase", render: (stage) => stage.stageName },
    { key: "deals", header: "Deals", render: (stage) => String(stage.dealCount) },
    { key: "value", header: "Waarde", render: (stage) => formatStageValue(stage, summary.currency) },
  ];

  return (
    <div data-testid="pipeline-summary">
      <DataTable
        columns={columns}
        rows={summary.stages}
        rowKey={(stage) => stage.stageId}
        label={`Pijplijn: ${summary.pipelineName}`}
      />
    </div>
  );
}
