"use client";

// Shared list-page body for contacts/companies/opportunities: search +
// tag filter + loading/empty/error + table + prev/next pager. Built on
// `useCrmList` (lib/hooks/useCrmList.ts); each entity's own list page
// supplies only its columns and copy.
import type { DataTableColumn } from "@/components/ui/DataTable";
import { DataTable } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import type { ListResult } from "@/lib/api/crm";
import type { ApiQueryState } from "@/lib/hooks/useApiQuery";

export type CrmListViewProps<T> = {
  query: ApiQueryState<ListResult<T>> & {
    refetch: () => void;
    searchInput: string;
    setSearchInput: (value: string) => void;
    tag: string;
    setTag: (value: string) => void;
    offset: number;
    pageSize: number;
    nextPage: () => void;
    prevPage: () => void;
  };
  columns: DataTableColumn<T>[];
  rowKey: (row: T) => string;
  getRowHref?: (row: T) => string;
  searchPlaceholder: string;
  emptyTitle: string;
  emptyDescription: string;
  emptyAction?: React.ReactNode;
};

export function CrmListView<T>({
  query,
  columns,
  rowKey,
  getRowHref,
  searchPlaceholder,
  emptyTitle,
  emptyDescription,
  emptyAction,
}: CrmListViewProps<T>) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <Input
            label="Search"
            placeholder={searchPlaceholder}
            value={query.searchInput}
            onChange={(event) => query.setSearchInput(event.target.value)}
          />
        </div>
        <div style={{ minWidth: 160 }}>
          <Input
            label="Tag"
            placeholder="Filter by tag name"
            value={query.tag}
            onChange={(event) => query.setTag(event.target.value)}
          />
        </div>
      </div>

      {query.status === "loading" ? <LoadingState label="Loading…" /> : null}

      {query.status === "error" ? <ApiErrorPanel error={query.error} onRetry={query.refetch} /> : null}

      {query.status === "success" && query.data.results.length === 0 ? (
        <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />
      ) : null}

      {query.status === "success" && query.data.results.length > 0 ? (
        <>
          <DataTable
            columns={columns}
            rows={query.data.results}
            rowKey={rowKey}
            getRowHref={getRowHref}
          />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
              Showing {query.offset + 1}–{query.offset + query.data.results.length}
            </span>
            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              <Button
                variant="secondary"
                size="sm"
                onClick={query.prevPage}
                disabled={query.offset === 0}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={query.nextPage}
                disabled={!query.data.hasMore}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
