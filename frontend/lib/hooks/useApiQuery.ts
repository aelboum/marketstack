"use client";

// Shared "load this GET, handle loading/error/refetch" shape -- every
// UI-2 list view (agency dashboard's client count, the clients list,
// client detail's lookup) needs the identical three states. Not a data-
// cache: nothing is stored beyond the current component's lifetime,
// there is no cross-component sharing, no stale-while-revalidate policy
// -- exactly "keep it simple" (docs/ROADMAP.md UI Track's UI-2 scope,
// item 14: "Do not implement a custom client-side cache framework unless
// the existing application already has one").
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api/errors";

export type ApiQueryState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };

export function useApiQuery<T>(fetcher: () => Promise<T>, deps: unknown[]): ApiQueryState<T> & {
  refetch: () => void;
} {
  const [state, setState] = useState<ApiQueryState<T>>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    fetcher()
      .then((data) => {
        if (!cancelled) setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError("network", "Something went wrong talking to the backend.");
        setState({ status: "error", error: apiError });
      });

    return () => {
      cancelled = true;
    };
    // `deps` is the caller's own explicit dependency list (mirrors
    // useEffect's own contract); `fetcher` is intentionally excluded --
    // callers pass a fresh closure each render, so including it would
    // refetch on every render instead of only when `deps` actually change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken]);

  const refetch = useCallback(() => setReloadToken((token) => token + 1), []);

  return { ...state, refetch };
}
