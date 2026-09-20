"use client";

import Link from "next/link";
import { listContacts, type Contact } from "@/lib/api/crm";
import { useCrmList } from "@/lib/hooks/useCrmList";
import { CrmListView } from "./CrmListView";
import type { DataTableColumn } from "@/components/ui/DataTable";

const columns: DataTableColumn<Contact>[] = [
  { key: "name", header: "Name", render: (c) => `${c.first_name} ${c.last_name}` },
  { key: "email", header: "Email", render: (c) => c.email ?? "—" },
  { key: "phone", header: "Phone", render: (c) => c.phone ?? "—" },
];

export function ContactsList({
  tenantId,
  reloadKey,
  onCreate,
}: {
  tenantId: string;
  reloadKey?: unknown;
  onCreate?: React.ReactNode;
}) {
  const query = useCrmList(listContacts, tenantId, reloadKey);

  const companyColumns: DataTableColumn<Contact>[] = [
    ...columns,
    {
      key: "company",
      header: "Company",
      render: (c) =>
        c.company_id ? (
          <Link href={`/t/${tenantId}/crm/companies/${c.company_id}`} onClick={(e) => e.stopPropagation()}>
            View company
          </Link>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <CrmListView
      query={query}
      columns={companyColumns}
      rowKey={(c) => c.id}
      getRowHref={(c) => `/t/${tenantId}/crm/contacts/${c.id}`}
      searchPlaceholder="Search contacts…"
      emptyTitle="No contacts yet"
      emptyDescription="Contacts created for this tenant will appear here."
      emptyAction={onCreate}
    />
  );
}
