// Semantic, reusable state components built on StatePanel -- import
// these across the app instead of writing a bespoke "no data yet" or
// "couldn't load" block per page (UI-1/UI-8 requirement: consistent
// loading/error/empty/permission-denied states, not duplicated per page).
"use client";

import { StatePanel, Spinner } from "./StatePanel";
import { Button } from "./Button";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <StatePanel
      icon={<Spinner label={label} />}
      title={label}
      inline
      role="status"
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <StatePanel
      icon={<span aria-hidden="true">□</span>}
      title={title}
      description={description}
      action={action}
      tone="neutral"
    />
  );
}

export function ErrorState({
  title = "Something went wrong",
  description,
  onRetry,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <StatePanel
      icon={<span aria-hidden="true">!</span>}
      title={title}
      description={description}
      tone="danger"
      role="alert"
      action={
        onRetry ? (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    />
  );
}

export function PermissionDeniedState({
  title = "Not found, or you don't have access",
  description = "This may not exist, or your current role may not include access to it. If you believe this is wrong, check with whoever manages your access.",
}: {
  title?: string;
  description?: string;
}) {
  // Deliberately does not claim to know which of the two is true -- the
  // backend's own non-enumeration design (product/crm/routes.py et al.,
  // see lib/api/errors.ts's ApiErrorKind doc comment) never tells the
  // frontend either, and the frontend must not appear to know more than
  // the backend actually disclosed.
  return (
    <StatePanel
      icon={<span aria-hidden="true">⊘</span>}
      title={title}
      description={description}
      tone="warning"
      role="alert"
    />
  );
}

export function UnauthorizedState({ onSignIn }: { onSignIn: () => void }) {
  return (
    <StatePanel
      icon={<span aria-hidden="true">⊘</span>}
      title="Your session has expired"
      description="Please sign in again to continue."
      tone="warning"
      role="alert"
      action={
        <Button variant="primary" size="sm" onClick={onSignIn}>
          Sign in
        </Button>
      }
    />
  );
}
