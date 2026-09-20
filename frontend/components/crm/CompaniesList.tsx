"use client";

import { listCompanies, type Company } from "@/lib/api/crm";
import { useCrmList } from "@/lib/hooks/useCrmList";
import { CrmListView } from "./CrmListView";
import type { DataTableColumn } from "@/components/ui/DataTable";

const columns: DataTableColumn<Company>[] = [
  { key: "name", header: "Name", render: (c) => c.name },
  { key: "domain", header: "Domain", render: (c) => c.domain ?? "—" },
  { key: "phone", header: "Phone", render: (c) => c.phone ?? "—" },
];

export function CompaniesList({
  tenantId,
  reloadKey,
  onCreate,
}: {
  tenantId: string;
  reloadKey?: unknown;
  onCreate?: React.ReactNode;
}) {
  const query = useCrmList(listCompanies, tenantId, reloadKey);

  return (
    <CrmListView
      query={query}
      columns={columns}
      rowKey={(c) => c.id}
      getRowHref={(c) => `/t/${tenantId}/crm/companies/${c.id}`}
      searchPlaceholder="Search companies…"
      emptyTitle="No companies yet"
      emptyDescription="Companies created for this tenant will appear here."
      emptyAction={onCreate}
    />
  );
}
