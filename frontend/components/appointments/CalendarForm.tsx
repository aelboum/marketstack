"use client";

// Create/edit a calendar. All three fields map 1:1 onto
// `CreateCalendarRequest`/`UpdateCalendarRequest`; PATCH treats `null`
// as "leave unchanged", so edit mode sends only what actually changed.
//
// `owner_user_id` is a raw user-id input, not a picker: there is still
// no "list tenant members" endpoint anywhere in this product's API (the
// same documented gap UI-2's delegation forms and UI-4's
// AssignThreadForm each already flagged). The backend validates it --
// an owner without calendar-read in the tenant comes back as the same
// non-enumerating 404 everything else uses -- so the UI offers the
// signed-in user's own id as a convenience and lets the backend decide.
import { useState } from "react";
import {
  createCalendar,
  updateCalendar,
  type Calendar,
} from "@/lib/api/appointments";
import {
  MAX_CALENDAR_NAME_LENGTH,
  browserTimeZone,
  supportedTimeZones,
} from "@/lib/appointments/datetime";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { useSession } from "@/lib/auth/session-context";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function CalendarForm({
  tenantId,
  calendar,
  onSaved,
}: {
  tenantId: string;
  /** Omit to create; pass an existing calendar to edit it. */
  calendar?: Calendar;
  onSaved: (calendar: Calendar) => void;
}) {
  const { user } = useSession();
  const [name, setName] = useState(calendar?.name ?? "");
  const [ownerUserId, setOwnerUserId] = useState(calendar?.owner_user_id ?? user?.user_id ?? "");
  const [timezone, setTimezone] = useState(calendar?.timezone ?? browserTimeZone());

  const zones = supportedTimeZones();

  const { state, run } = useAsyncAction(() =>
    calendar
      ? updateCalendar(tenantId, calendar.id, {
          name: name !== calendar.name ? name : null,
          owner_user_id: ownerUserId !== calendar.owner_user_id ? ownerUserId : null,
          timezone: timezone !== calendar.timezone ? timezone : null,
        })
      : createCalendar(tenantId, {
          name,
          owner_user_id: ownerUserId.trim(),
          timezone,
        }),
  );

  const nameTooLong = name.length > MAX_CALENDAR_NAME_LENGTH;
  const canSubmit = name.trim().length > 0 && ownerUserId.trim().length > 0 && !nameTooLong;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const saved = await run();
        if (saved) onSaved(saved);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <Input
        label="Name"
        required
        value={name}
        onChange={(event) => setName(event.target.value)}
        error={nameTooLong ? `Name must be ${MAX_CALENDAR_NAME_LENGTH} characters or fewer.` : undefined}
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <Input
          label="Owner user ID"
          required
          value={ownerUserId}
          onChange={(event) => setOwnerUserId(event.target.value)}
          placeholder="00000000-0000-0000-0000-000000000000"
        />
        {user?.user_id && ownerUserId !== user.user_id ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => setOwnerUserId(user.user_id)}>
            Use my user ID
          </Button>
        ) : null}
      </div>

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Timezone — availability rules are interpreted in this zone
        </span>
        {zones ? (
          <select value={timezone} onChange={(event) => setTimezone(event.target.value)}>
            {zones.includes(timezone) ? null : <option value={timezone}>{timezone}</option>}
            {zones.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
        ) : (
          <input
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            placeholder="Europe/Amsterdam"
            style={{
              padding: "var(--space-2)",
              border: "1px solid var(--color-border-strong)",
              borderRadius: "var(--radius-sm)",
            }}
          />
        )}
      </label>

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Saving…" : calendar ? "Save changes" : "Create calendar"}
      </Button>
    </form>
  );
}
