"use client";

// Stage names aren't on the opportunity response itself (only
// `stage_id`/`pipeline_id`) -- `product/crm/routes.py` has no per-
// opportunity join. Pipelines/stages are tenant-wide, small,
// unpaginated lists (`GET .../pipelines`, `GET .../pipelines/{id}/stages`),
// so this list fetches them once and builds a lookup, rather than one
// request per row.
import { useEffect, useState } from "react";
import { listOpportunities, listPipelines, listStages, type Opportunity } from "@/lib/api/crm";
import { formatMoney } from "@/lib/crm/money";
import { useCrmList } from "@/lib/hooks/useCrmList";
import { CrmListView } from "./CrmListView";
import type { DataTableColumn } from "@/components/ui/DataTable";

export function OpportunitiesList({
  tenantId,
  reloadKey,
  onCreate,
}: {
  tenantId: string;
  reloadKey?: unknown;
  onCreate?: React.ReactNode;
}) {
  const query = useCrmList(listOpportunities, tenantId, reloadKey);
  const [stageNames, setStageNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    listPipelines(tenantId).then(async (pipelines) => {
      const entries: [string, string][] = [];
      for (const pipeline of pipelines) {
        const stages = await listStages(tenantId, pipeline.id);
        for (const stage of stages) entries.push([stage.id, `${pipeline.name} · ${stage.name}`]);
      }
      if (!cancelled) setStageNames(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const columns: DataTableColumn<Opportunity>[] = [
    { key: "name", header: "Name", render: (o) => o.name },
    { key: "stage", header: "Stage", render: (o) => stageNames[o.stage_id] ?? "…" },
    { key: "amount", header: "Amount", render: (o) => formatMoney(o.amount) },
  ];

  return (
    <CrmListView
      query={query}
      columns={columns}
      rowKey={(o) => o.id}
      getRowHref={(o) => `/t/${tenantId}/crm/opportunities/${o.id}`}
      searchPlaceholder="Search opportunities…"
      emptyTitle="No opportunities yet"
      emptyDescription="Opportunities created for this tenant will appear here."
      emptyAction={onCreate}
    />
  );
}
