"use client";

// Small, shared piece of UI state every UI-2 mutation (create client,
// invite member, create/revoke delegation or deny, request/approve/
// deny/revoke support access) needs identically: track in-flight/error/
// success, refuse a second submit while one is already running, surface
// an ApiError through the same error-classification lib/api/errors.ts
// already defines. Not a client-side cache/store -- it holds no server
// state, only "what is this one action currently doing."
import { useCallback, useRef, useState } from "react";
import { ApiError } from "@/lib/api/errors";

export type AsyncActionState<T> =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };

export function useAsyncAction<Args extends unknown[], T>(fn: (...args: Args) => Promise<T>) {
  const [state, setState] = useState<AsyncActionState<T>>({ status: "idle" });
  // A ref, not `state.status`, drives the duplicate-submit guard -- a
  // `useCallback` closes over whatever `state` was at the render it was
  // created in, which goes stale across renders where `fn` itself is
  // referentially stable; a ref is always read at call time instead.
  const pendingRef = useRef(false);

  const run = useCallback(
    async (...args: Args) => {
      // Duplicate-submission protection: a second call while one is
      // already pending is a no-op, not a second request.
      if (pendingRef.current) return;
      pendingRef.current = true;
      setState({ status: "pending" });
      try {
        const data = await fn(...args);
        setState({ status: "success", data });
        return data;
      } catch (error) {
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError("network", "Something went wrong talking to the backend.");
        setState({ status: "error", error: apiError });
        return undefined;
      } finally {
        pendingRef.current = false;
      }
    },
    [fn],
  );

  const reset = useCallback(() => setState({ status: "idle" }), []);

  return { state, run, reset, isPending: state.status === "pending" };
}
