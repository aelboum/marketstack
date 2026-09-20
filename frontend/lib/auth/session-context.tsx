"use client";

// Authenticated-vs-unauthenticated application state, centralized once
// (UI-1 requirement) instead of every page re-implementing the
// check-/auth/me-on-mount pattern the original Phase 1.6
// app/dashboard/page.tsx used inline. That page's own logic is the
// direct ancestor of this provider -- same endpoint, same credentialed
// fetch, same redirect-on-401 behavior, just centralized and reusable.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api/errors";
import { getCurrentUser, logout as logoutRequest, type CurrentUser } from "@/lib/auth/api";

export type SessionStatus = "loading" | "authenticated" | "unauthenticated";

export type SessionState = {
  status: SessionStatus;
  user: CurrentUser | null;
  /** Re-runs the /auth/me check (e.g. after returning from the OIDC flow). */
  refresh: () => void;
  /** Ends the session server-side, then flips local state. */
  logout: () => Promise<void>;
  /**
   * Any later API call that gets a 401 ApiError should call this instead
   * of leaving the UI showing stale "authenticated" state -- see
   * lib/api/errors.ts's ApiErrorKind "unauthorized".
   */
  markSessionExpired: () => void;
};

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [generation, setGeneration] = useState(0);

  const refresh = useCallback(() => {
    setStatus("loading");
    setGeneration((g) => g + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    getCurrentUser(controller.signal)
      .then((current) => {
        if (cancelled) return;
        setUser(current);
        setStatus("authenticated");
      })
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        // Any failure to establish a session (401, network, ...) is
        // treated the same: there is no usable session. Only an
        // ApiError's `unauthorized`/`forbidden` kind is an expected,
        // non-exceptional outcome here; anything else still lands the
        // user on the signed-out state rather than an infinite spinner.
        setUser(null);
        setStatus("unauthenticated");
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [generation]);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } catch (error) {
      // Even if the backend logout call itself fails (e.g. the session
      // was already gone), the local state still transitions -- logout
      // must never appear to hang.
      if (!(error instanceof ApiError)) throw error;
    } finally {
      setUser(null);
      setStatus("unauthenticated");
    }
  }, []);

  const markSessionExpired = useCallback(() => {
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const value = useMemo(
    () => ({ status, user, refresh, logout, markSessionExpired }),
    [status, user, refresh, logout, markSessionExpired],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession() must be called inside a <SessionProvider>.");
  }
  return context;
}
