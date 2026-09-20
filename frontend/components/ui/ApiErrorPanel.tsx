"use client";

// Renders the one correct full-page state for a failed API load,
// consistently, everywhere a UI-2 view fetches something
// (lib/hooks/useApiQuery.ts's `error` branch): 401 flips the shared
// session state (so the rest of the app also notices) and shows a
// sign-in prompt; a 403/tenant-scoped-404 shows the non-enumerating
// PermissionDeniedState (never a message implying which one it was --
// see lib/api/errors.ts's ApiErrorKind doc comment); anything else is a
// retryable ErrorState.
import { useEffect } from "react";
import { ApiError } from "@/lib/api/errors";
import { useSession } from "@/lib/auth/session-context";
import { loginUrl } from "@/lib/auth/api";
import { ErrorState, PermissionDeniedState, UnauthorizedState } from "./states";

export function ApiErrorPanel({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const { markSessionExpired } = useSession();

  useEffect(() => {
    if (error.kind === "unauthorized") {
      markSessionExpired();
    }
  }, [error, markSessionExpired]);

  if (error.kind === "unauthorized") {
    return <UnauthorizedState onSignIn={() => window.location.assign(loginUrl())} />;
  }
  if (error.kind === "forbidden") {
    return <PermissionDeniedState />;
  }
  return <ErrorState description={error.message} onRetry={onRetry} />;
}
