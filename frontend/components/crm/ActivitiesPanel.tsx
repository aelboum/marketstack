"use client";

// Tasks + notes attached to a contact/company/opportunity
// (`product/crm/activities.py`, mounted per-parent in
// `product/crm/routes.py`). One panel, reused on every detail page --
// the three parent kinds share the identical activity shape and routes,
// differing only in which path segment/id they attach to
// (`ActivityParent`, lib/api/crm.ts).
import { useState } from "react";
import {
  completeTask,
  createNote,
  createTask,
  deleteNote,
  deleteTask,
  listActivities,
  type Activity,
  type ActivityParent,
} from "@/lib/api/crm";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { FormRow } from "@/components/ui/FormRow";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { Badge } from "@/components/ui/Badge";

function AddTaskForm({
  tenantId,
  parent,
  onCreated,
}: {
  tenantId: string;
  parent: ActivityParent;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const { state, run } = useAsyncAction(() => createTask(tenantId, parent, { title }));

  return (
    <FormRow
      onSubmit={async (event) => {
        event.preventDefault();
        if (!title.trim()) return;
        const created = await run();
        if (created) {
          setTitle("");
          onCreated();
        }
      }}
    >
      <div style={{ flex: 1 }}>
        <Input
          label="New task"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Follow up next week"
        />
      </div>
      <Button type="submit" size="sm" disabled={state.status === "pending" || !title.trim()}>
        Add
      </Button>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </FormRow>
  );
}

function AddNoteForm({
  tenantId,
  parent,
  onCreated,
}: {
  tenantId: string;
  parent: ActivityParent;
  onCreated: () => void;
}) {
  const [body, setBody] = useState("");
  const { state, run } = useAsyncAction(() => createNote(tenantId, parent, body));

  return (
    <FormRow
      onSubmit={async (event) => {
        event.preventDefault();
        if (!body.trim()) return;
        const created = await run();
        if (created) {
          setBody("");
          onCreated();
        }
      }}
    >
      <div style={{ flex: 1 }}>
        <Input
          label="New note"
          value={body}
          onChange={(event) => setBody(event.target.value)}
          placeholder="Notes from the call…"
        />
      </div>
      <Button type="submit" size="sm" disabled={state.status === "pending" || !body.trim()}>
        Add
      </Button>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
    </FormRow>
  );
}

function ActivityRow({
  tenantId,
  activity,
  onChanged,
}: {
  tenantId: string;
  activity: Activity;
  onChanged: () => void;
}) {
  const { run: runComplete, state: completeState } = useAsyncAction(() =>
    completeTask(tenantId, activity.id),
  );
  const { run: runDelete, state: deleteState } = useAsyncAction(() =>
    activity.kind === "task" ? deleteTask(tenantId, activity.id) : deleteNote(tenantId, activity.id),
  );
  const pending = completeState.status === "pending" || deleteState.status === "pending";

  return (
    <Card style={{ padding: "var(--space-3)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)" }}>
        <div style={{ minWidth: 0 }}>
          {activity.kind === "task" ? (
            <>
              <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
                <strong>{activity.title}</strong>
                {activity.completed_at ? <Badge tone="success">Done</Badge> : null}
              </div>
              {activity.description ? (
                <p style={{ margin: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
                  {activity.description}
                </p>
              ) : null}
            </>
          ) : (
            <p style={{ margin: 0 }}>{activity.body}</p>
          )}
        </div>
        <div style={{ display: "flex", gap: "var(--space-1)", flexShrink: 0 }}>
          {activity.kind === "task" && !activity.completed_at ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={pending}
              onClick={async () => {
                await runComplete();
                onChanged();
              }}
            >
              Complete
            </Button>
          ) : null}
          <Button
            variant="danger"
            size="sm"
            disabled={pending}
            onClick={async () => {
              await runDelete();
              onChanged();
            }}
          >
            Delete
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function ActivitiesPanel({ tenantId, parent }: { tenantId: string; parent: ActivityParent }) {
  const query = useApiQuery(() => listActivities(tenantId, parent), [tenantId, JSON.stringify(parent)]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <AddTaskForm tenantId={tenantId} parent={parent} onCreated={query.refetch} />
      <AddNoteForm tenantId={tenantId} parent={parent} onCreated={query.refetch} />

      {query.status === "loading" ? <LoadingState label="Loading activity…" /> : null}
      {query.status === "error" ? <ApiErrorPanel error={query.error} onRetry={query.refetch} /> : null}
      {query.status === "success" && query.data.length === 0 ? (
        <EmptyState title="No activity yet" description="Tasks and notes will appear here." />
      ) : null}
      {query.status === "success" && query.data.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          {query.data.map((activity) => (
            <ActivityRow
              key={activity.id}
              tenantId={tenantId}
              activity={activity}
              onChanged={query.refetch}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
