"use client";

// A minimal shared signal between the Unified Inbox's list pane
// (InboxShell, docs/ROADMAP.md Phase 30) and whatever action a sibling
// detail/create page just took (a new thread created, a message sent, an
// assignment changed) that should be reflected in the list's preview/
// needs-reply state. Not a data cache, not a generic pub/sub -- one
// `reloadKey` counter and one function to bump it, the same shape
// `useApiQuery`'s own `refetch` already uses internally, just shared
// across the layout/page boundary Next.js's own `children` prop cannot
// cross on its own.
import { createContext, useContext, useMemo, useState } from "react";

type InboxRefreshContextValue = {
  reloadKey: number;
  refresh: () => void;
};

const InboxRefreshContext = createContext<InboxRefreshContextValue | null>(null);

export function InboxRefreshProvider({ children }: { children: React.ReactNode }) {
  const [reloadKey, setReloadKey] = useState(0);
  const value = useMemo(
    () => ({ reloadKey, refresh: () => setReloadKey((key) => key + 1) }),
    [reloadKey],
  );
  return <InboxRefreshContext.Provider value={value}>{children}</InboxRefreshContext.Provider>;
}

/** Safe to call from a page not wrapped in `InboxRefreshProvider` (e.g. a
 * future standalone embed) -- returns a no-op `refresh()` rather than
 * throwing, since "there is nothing to refresh" is a legitimate context,
 * not a programmer error, unlike `useSession()`'s own required-provider
 * contract. */
export function useInboxRefresh(): InboxRefreshContextValue {
  const context = useContext(InboxRefreshContext);
  return context ?? { reloadKey: 0, refresh: () => {} };
}
