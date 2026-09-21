"use client";

// Weekly availability rules for one calendar. The wire format is
// (`day_of_week`, `start_time`, `end_time`) where the two times are
// **minutes since local midnight in the calendar's own timezone** and
// `day_of_week` is Python's `date.weekday()` -- 0 = Monday, not
// JavaScript's 0 = Sunday. Both conversions live in
// lib/appointments/datetime.ts and are unit-tested there, because
// getting either backwards publishes availability at the wrong time on
// the wrong day.
//
// The backend performs **no overlap validation** (verified in
// `availability.py::create_availability_rule()`): two overlapping rules
// on the same day are accepted and then produce duplicate slots. This
// panel therefore shows a warning when the rule being added overlaps one
// that already exists -- it does not block the submit, because the
// backend, not the frontend, is the authority on what is allowed.
import { useState } from "react";
import {
  createAvailabilityRule,
  deleteAvailabilityRule,
  listAvailabilityRules,
  type AvailabilityRule,
} from "@/lib/api/appointments";
import {
  DAY_NAMES,
  minutesToTimeInput,
  timeInputToMinutes,
} from "@/lib/appointments/datetime";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { FormRow } from "@/components/ui/FormRow";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

function RuleRow({
  tenantId,
  calendarId,
  rule,
  onChanged,
}: {
  tenantId: string;
  calendarId: string;
  rule: AvailabilityRule;
  onChanged: () => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { run, state } = useAsyncAction(() =>
    deleteAvailabilityRule(tenantId, calendarId, rule.id),
  );

  return (
    <li
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: "var(--space-2)",
        padding: "var(--space-2) 0",
        borderBottom: "1px solid var(--color-border)",
        flexWrap: "wrap",
      }}
    >
      <span style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
        <Badge tone="accent">{DAY_NAMES[rule.day_of_week] ?? `Day ${rule.day_of_week}`}</Badge>
        <span style={{ fontSize: "var(--font-size-sm)" }}>
          {minutesToTimeInput(rule.start_time)} – {minutesToTimeInput(rule.end_time)}
        </span>
      </span>
      <span style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
        {state.status === "error" ? (
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        ) : null}
        <Button variant="danger" size="sm" onClick={() => setConfirmOpen(true)}>
          Remove
        </Button>
      </span>
      <ConfirmDialog
        open={confirmOpen}
        title="Remove this availability rule?"
        description="New bookable slots will no longer be generated from it. Appointments already booked are not affected."
        confirmLabel="Remove"
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          await run();
          setConfirmOpen(false);
          onChanged();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </li>
  );
}

function overlapsExisting(
  rules: AvailabilityRule[],
  dayOfWeek: number,
  start: number,
  end: number,
): boolean {
  return rules.some(
    (rule) => rule.day_of_week === dayOfWeek && start < rule.end_time && end > rule.start_time,
  );
}

export function AvailabilityRulesPanel({
  tenantId,
  calendarId,
}: {
  tenantId: string;
  calendarId: string;
}) {
  const query = useApiQuery(
    () => listAvailabilityRules(tenantId, calendarId),
    [tenantId, calendarId],
  );
  const [dayOfWeek, setDayOfWeek] = useState(0);
  const [startValue, setStartValue] = useState("09:00");
  const [endValue, setEndValue] = useState("17:00");

  const startMinutes = timeInputToMinutes(startValue);
  const endMinutes = endValue === "24:00" ? 1440 : timeInputToMinutes(endValue);

  const { state, run } = useAsyncAction(() =>
    createAvailabilityRule(tenantId, calendarId, {
      day_of_week: dayOfWeek,
      start_time: startMinutes as number,
      end_time: endMinutes as number,
    }),
  );

  const timesValid =
    startMinutes !== null && endMinutes !== null && endMinutes > startMinutes;
  const existing = query.status === "success" ? query.data : [];
  const wouldOverlap =
    timesValid && overlapsExisting(existing, dayOfWeek, startMinutes, endMinutes);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {query.status === "loading" ? <LoadingState label="Loading availability…" /> : null}
      {query.status === "error" ? (
        <ApiErrorPanel error={query.error} onRetry={query.refetch} />
      ) : null}
      {query.status === "success" ? (
        query.data.length === 0 ? (
          <EmptyState
            title="No availability yet"
            description="Add a weekly rule below. Bookable slots are generated from these rules, in this calendar's timezone."
          />
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {query.data.map((rule) => (
              <RuleRow
                key={rule.id}
                tenantId={tenantId}
                calendarId={calendarId}
                rule={rule}
                onChanged={query.refetch}
              />
            ))}
          </ul>
        )
      ) : null}

      <Card>
        <h3 style={{ marginTop: 0, fontSize: "var(--font-size-sm)" }}>Add a weekly rule</h3>
        <FormRow
          onSubmit={async (event) => {
            event.preventDefault();
            if (!timesValid) return;
            const created = await run();
            if (created) query.refetch();
          }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Day</span>
            <select
              aria-label="Day"
              value={dayOfWeek}
              onChange={(event) => setDayOfWeek(Number(event.target.value))}
            >
              {DAY_NAMES.map((label, index) => (
                <option key={label} value={index}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Start</span>
            <input
              aria-label="Start time"
              type="time"
              value={startValue}
              onChange={(event) => setStartValue(event.target.value)}
              style={{
                padding: "var(--space-2)",
                border: "1px solid var(--color-border-strong)",
                borderRadius: "var(--radius-sm)",
              }}
            />
          </label>

          <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
            <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>End</span>
            <input
              aria-label="End time"
              type="time"
              value={endValue}
              onChange={(event) => setEndValue(event.target.value)}
              style={{
                padding: "var(--space-2)",
                border: "1px solid var(--color-border-strong)",
                borderRadius: "var(--radius-sm)",
              }}
            />
          </label>

          <Button type="submit" disabled={state.status === "pending" || !timesValid}>
            {state.status === "pending" ? "Adding…" : "Add rule"}
          </Button>
        </FormRow>

        {!timesValid && startValue && endValue ? (
          <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
            End time must be after start time.
          </p>
        ) : null}
        {wouldOverlap ? (
          <InlineNotice tone="warning">
            This overlaps a rule that already exists for {DAY_NAMES[dayOfWeek]}. The backend accepts
            overlapping rules, but they generate duplicate bookable slots.
          </InlineNotice>
        ) : null}
        {state.status === "error" ? (
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        ) : null}
      </Card>
    </div>
  );
}
