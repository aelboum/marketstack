"use client";

// Bookable slots for one calendar over a date range.
//
// **Every slot shown here came from the backend.** Nothing is computed,
// extended, or filled in client-side: `compute_available_slots()` is the
// only thing that knows the calendar's rules, its timezone, its DST
// transitions, and which slots are already taken by a confirmed
// appointment. The UI's job is to render that answer and let a staff
// member pick one -- not to reason about availability itself.
//
// Slots come back as UTC instants for a calendar that carries its own
// IANA timezone, so they are rendered *in the calendar's zone*: an
// administrator in another country must see the times the contact will
// see, not their own.
//
// The date-range and duration inputs are validated against the real
// backend limits (`MAX_AVAILABILITY_QUERY_DAYS`,
// `MIN/MAX_SLOT_DURATION_MINUTES`) so an out-of-range query is caught
// before it becomes a 400 -- the backend still enforces them.
import { useState } from "react";
import { listAvailableSlots, type AvailableSlot } from "@/lib/api/appointments";
import {
  MAX_AVAILABILITY_QUERY_DAYS,
  MAX_SLOT_DURATION_MINUTES,
  MIN_SLOT_DURATION_MINUTES,
  dateSpanDays,
  dayKeyInTimeZone,
  formatTimeInTimeZone,
  toDateInput,
} from "@/lib/appointments/datetime";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

function groupByDay(slots: AvailableSlot[], timeZone: string): [string, AvailableSlot[]][] {
  const groups = new Map<string, AvailableSlot[]>();
  for (const slot of slots) {
    const key = dayKeyInTimeZone(slot.starts_at, timeZone);
    const bucket = groups.get(key);
    if (bucket) bucket.push(slot);
    else groups.set(key, [slot]);
  }
  return [...groups.entries()];
}

export function AvailableSlotsPicker({
  tenantId,
  calendarId,
  timeZone,
  selectedSlotStart,
  onSelect,
}: {
  tenantId: string;
  calendarId: string;
  /** The calendar's own IANA zone -- slots are displayed in it. */
  timeZone: string;
  /** `starts_at` of the currently chosen slot, when used as a picker. */
  selectedSlotStart?: string | null;
  /** Omit to render as a read-only availability view. */
  onSelect?: (slot: AvailableSlot) => void;
}) {
  const today = toDateInput(new Date());
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(today);
  const [duration, setDuration] = useState(30);
  // Only a submitted query hits the API -- typing in the date fields
  // must not fire a request per keystroke.
  const [applied, setApplied] = useState<{
    date_from: string;
    date_to: string;
    slot_duration_minutes: number;
  } | null>(null);

  const span = dateSpanDays(dateFrom, dateTo);
  const rangeInvalid = span === null || span < 0;
  const rangeTooLong = span !== null && span > MAX_AVAILABILITY_QUERY_DAYS;
  const durationInvalid =
    !Number.isFinite(duration) ||
    duration < MIN_SLOT_DURATION_MINUTES ||
    duration > MAX_SLOT_DURATION_MINUTES;
  const canSearch = !rangeInvalid && !rangeTooLong && !durationInvalid;

  const query = useApiQuery(
    () =>
      applied
        ? listAvailableSlots(tenantId, calendarId, applied)
        : Promise.resolve<AvailableSlot[]>([]),
    [tenantId, calendarId, applied],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!canSearch) return;
          setApplied({
            date_from: dateFrom,
            date_to: dateTo,
            slot_duration_minutes: duration,
          });
        }}
        style={{ display: "flex", gap: "var(--space-2)", alignItems: "flex-end", flexWrap: "wrap" }}
      >
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>From</span>
          <input
            aria-label="From date"
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            style={{
              padding: "var(--space-2)",
              border: "1px solid var(--color-border-strong)",
              borderRadius: "var(--radius-sm)",
            }}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>To</span>
          <input
            aria-label="To date"
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            style={{
              padding: "var(--space-2)",
              border: "1px solid var(--color-border-strong)",
              borderRadius: "var(--radius-sm)",
            }}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
            Slot length (minutes)
          </span>
          <input
            aria-label="Slot length in minutes"
            type="number"
            min={MIN_SLOT_DURATION_MINUTES}
            max={MAX_SLOT_DURATION_MINUTES}
            value={duration}
            onChange={(event) => setDuration(Number(event.target.value))}
            style={{
              width: 120,
              padding: "var(--space-2)",
              border: "1px solid var(--color-border-strong)",
              borderRadius: "var(--radius-sm)",
            }}
          />
        </label>
        <Button type="submit" disabled={!canSearch}>
          Find slots
        </Button>
      </form>

      {rangeInvalid && !rangeTooLong ? (
        <InlineNotice tone="warning">The end date must not be before the start date.</InlineNotice>
      ) : null}
      {rangeTooLong ? (
        <InlineNotice tone="warning">
          The date range must be {MAX_AVAILABILITY_QUERY_DAYS} days or fewer.
        </InlineNotice>
      ) : null}
      {durationInvalid ? (
        <InlineNotice tone="warning">
          Slot length must be between {MIN_SLOT_DURATION_MINUTES} and {MAX_SLOT_DURATION_MINUTES}{" "}
          minutes.
        </InlineNotice>
      ) : null}

      {applied === null ? (
        <p style={{ margin: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
          Choose a date range and slot length, then search for bookable slots.
        </p>
      ) : query.status === "loading" ? (
        <LoadingState label="Loading available slots…" />
      ) : query.status === "error" ? (
        <ApiErrorPanel error={query.error} onRetry={query.refetch} />
      ) : query.data.length === 0 ? (
        <EmptyState
          title="No available slots"
          description="Nothing is bookable in this range. Check the calendar's availability rules, or try a different range."
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          <p style={{ margin: 0, fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
            Times shown in {timeZone}.
          </p>
          {groupByDay(query.data, timeZone).map(([day, slots]) => (
            <section key={day} aria-label={day}>
              <h3 style={{ fontSize: "var(--font-size-sm)", margin: "0 0 var(--space-2)" }}>{day}</h3>
              <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                {slots.map((slot) =>
                  onSelect ? (
                    <Button
                      key={slot.starts_at}
                      variant={selectedSlotStart === slot.starts_at ? "primary" : "secondary"}
                      size="sm"
                      aria-pressed={selectedSlotStart === slot.starts_at}
                      onClick={() => onSelect(slot)}
                    >
                      {formatTimeInTimeZone(slot.starts_at, timeZone)}
                    </Button>
                  ) : (
                    <span
                      key={slot.starts_at}
                      style={{
                        padding: "var(--space-1) var(--space-2)",
                        border: "1px solid var(--color-border)",
                        borderRadius: "var(--radius-sm)",
                        fontSize: "var(--font-size-sm)",
                      }}
                    >
                      {formatTimeInTimeZone(slot.starts_at, timeZone)}
                    </span>
                  ),
                )}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
