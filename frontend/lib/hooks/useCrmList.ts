"use client";

// Shared paged/searchable-list state for every CRM list
// (contacts/companies/opportunities) -- one place for the
// search-debounce + tag-filter + offset-pagination pattern instead of
// three near-identical re-implementations. Built on `useApiQuery`
// (loading/error/refetch) and `useDebouncedValue` (avoid a request per
// keystroke); the offset resets to 0 whenever a filter changes, so a
// search never leaves the user stranded on a now-out-of-range page.
import { useEffect, useState } from "react";
import { useApiQuery } from "./useApiQuery";
import { useDebouncedValue } from "./useDebouncedValue";
import type { ListParams, ListResult } from "@/lib/api/crm";

const PAGE_SIZE = 25;

export function useCrmList<T>(
  fetcher: (tenantId: string, params: ListParams) => Promise<ListResult<T>>,
  tenantId: string,
  reloadKey?: unknown,
) {
  const [searchInput, setSearchInput] = useState("");
  const debouncedSearch = useDebouncedValue(searchInput);
  const [tag, setTag] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setOffset(0);
  }, [debouncedSearch, tag]);

  const query = useApiQuery<ListResult<T>>(
    () => fetcher(tenantId, { limit: PAGE_SIZE, offset, q: debouncedSearch, tag }),
    [tenantId, debouncedSearch, tag, offset, reloadKey],
  );

  return {
    ...query,
    searchInput,
    setSearchInput,
    tag,
    setTag,
    offset,
    pageSize: PAGE_SIZE,
    nextPage: () => setOffset((current) => current + PAGE_SIZE),
    prevPage: () => setOffset((current) => Math.max(0, current - PAGE_SIZE)),
  };
}
