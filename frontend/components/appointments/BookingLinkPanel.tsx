"use client";

// The public booking link for one calendar. `POST .../booking-link` is
// get-or-create and returns the raw token only -- the public URL is
// assembled here from `API_BASE_URL`, exactly the way UI-5's form detail
// page assembles a form's public submit URL from its `form_token`.
//
// The token is only fetched when a staff member asks for it: the route
// is a POST that *creates* the link on first call, so firing it on page
// load would mint a public booking link for every calendar anyone
// happens to open.
import { useState } from "react";
import { getOrCreateBookingLink } from "@/lib/api/appointments";
import { API_BASE_URL } from "@/lib/api/config";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function BookingLinkPanel({
  tenantId,
  calendarId,
}: {
  tenantId: string;
  calendarId: string;
}) {
  const [token, setToken] = useState<string | null>(null);
  const { state, run } = useAsyncAction(() => getOrCreateBookingLink(tenantId, calendarId));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <p style={{ margin: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
        Contacts book themselves through a public, unauthenticated endpoint. The link is created on
        first request and stays the same afterwards.
      </p>

      {token === null ? (
        <div>
          <Button
            variant="secondary"
            disabled={state.status === "pending"}
            onClick={async () => {
              const result = await run();
              if (result) setToken(result.link_token);
            }}
          >
            {state.status === "pending" ? "Working…" : "Show booking link"}
          </Button>
        </div>
      ) : (
        <p style={{ margin: 0, fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Public booking endpoint (POST, unauthenticated):
          <br />
          <code style={{ wordBreak: "break-all" }}>
            {`${API_BASE_URL}/v1/appointments/book/${token}`}
          </code>
        </p>
      )}

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
    </div>
  );
}
