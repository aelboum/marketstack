"use client";

// The workflow's version history, its published (live) configuration,
// and its editable draft -- the durable engine's real versioning model,
// rendered plainly rather than flattened away.
//
// A version is "live" only once published (`PUT` on it is refused by
// the backend after that point), so editing and publishing are always
// two separate, explicit steps here: this panel never auto-publishes
// what it saves.
import { useState } from "react";
import {
  listVersions,
  publishVersion,
  type Workflow,
  type WorkflowVersion,
} from "@/lib/api/automation";
import { ACTION_LABELS, TRIGGER_LABELS } from "@/lib/automation/actions";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { extractActionStep } from "./WorkflowStepForm";
import { VersionEditor } from "./VersionEditor";

function VersionSummary({ version }: { version: WorkflowVersion }) {
  const step = extractActionStep(version);
  return (
    <dl
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr",
        gap: "var(--space-1) var(--space-3)",
        margin: 0,
        fontSize: "var(--font-size-sm)",
      }}
    >
      <dt style={{ color: "var(--color-text-muted)" }}>Trigger</dt>
      <dd style={{ margin: 0 }}>
        {version.trigger_type ? TRIGGER_LABELS[version.trigger_type] : "Manual start only"}
      </dd>
      <dt style={{ color: "var(--color-text-muted)" }}>Action</dt>
      <dd style={{ margin: 0 }}>
        {step ? ACTION_LABELS[step.action_type] : `Step "${version.start_step_key}" (not editable here)`}
      </dd>
    </dl>
  );
}

export function VersionsPanel({
  tenantId,
  workflowId,
  workflow,
}: {
  tenantId: string;
  workflowId: string;
  workflow: Workflow;
}) {
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(false);
  const [confirmPublishOpen, setConfirmPublishOpen] = useState(false);

  // Real backend limit (MAX_PAGE_SIZE); versions this UI creates are few,
  // so one page covers the normal case. A tenant with more than 100
  // versions on one workflow -- not reachable through this UI -- would
  // need real pagination here, which is a documented limitation, not a
  // silent truncation.
  const versionsQuery = useApiQuery(
    () => listVersions(tenantId, workflowId, { limit: 100 }),
    [tenantId, workflowId, reloadKey],
  );

  const { run: runPublish, state: publishState } = useAsyncAction((versionId: string) =>
    publishVersion(tenantId, workflowId, versionId),
  );

  if (versionsQuery.status === "loading") return <LoadingState label="Loading versions…" />;
  if (versionsQuery.status === "error") {
    return <ApiErrorPanel error={versionsQuery.error} onRetry={versionsQuery.refetch} />;
  }

  const versions = versionsQuery.data.results;
  const publishedVersion =
    versions.find((v) => v.id === workflow.current_published_version_id) ?? null;
  const draftVersion =
    versions
      .filter((v) => v.status === "draft")
      .sort((a, b) => b.version_number - a.version_number)[0] ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      <section aria-labelledby="published-version-heading">
        <h3 id="published-version-heading" style={{ fontSize: "var(--font-size-sm)", margin: "0 0 var(--space-2)" }}>
          Live configuration
        </h3>
        <Card>
          {publishedVersion ? (
            <>
              <div style={{ marginBottom: "var(--space-2)" }}>
                <Badge tone="accent">Version {publishedVersion.version_number}</Badge>
              </div>
              <VersionSummary version={publishedVersion} />
            </>
          ) : (
            <p style={{ margin: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
              No version has been published yet -- this automation cannot run until one is.
            </p>
          )}
        </Card>
      </section>

      <section aria-labelledby="draft-version-heading">
        <h3 id="draft-version-heading" style={{ fontSize: "var(--font-size-sm)", margin: "0 0 var(--space-2)" }}>
          Draft
        </h3>
        <Card>
          {editing ? (
            <VersionEditor
              tenantId={tenantId}
              workflowId={workflowId}
              draftVersion={draftVersion}
              seedFrom={publishedVersion}
              onSaved={() => {
                setEditing(false);
                setReloadKey((k) => k + 1);
              }}
            />
          ) : draftVersion ? (
            <>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: "var(--space-2)",
                  flexWrap: "wrap",
                  gap: "var(--space-2)",
                }}
              >
                <Badge tone="warning">Version {draftVersion.version_number} -- draft</Badge>
                <div style={{ display: "flex", gap: "var(--space-2)" }}>
                  <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                    Edit
                  </Button>
                  <Button size="sm" onClick={() => setConfirmPublishOpen(true)}>
                    Publish
                  </Button>
                </div>
              </div>
              <VersionSummary version={draftVersion} />
            </>
          ) : (
            <>
              <p style={{ marginTop: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
                {publishedVersion
                  ? "No draft yet. Editing starts a new draft from the live configuration -- publishing it is a separate, explicit step."
                  : "No draft yet."}
              </p>
              <Button size="sm" onClick={() => setEditing(true)}>
                {publishedVersion ? "Edit" : "Configure"}
              </Button>
            </>
          )}

          {publishState.status === "error" ? (
            <InlineNotice tone="danger">{publishState.error.message}</InlineNotice>
          ) : null}
        </Card>
      </section>

      <ConfirmDialog
        open={confirmPublishOpen}
        title="Publish this draft?"
        description="It becomes the live configuration immediately. If this workflow is active and has a trigger, matching events will start using it right away."
        confirmLabel="Publish"
        pending={publishState.status === "pending"}
        onConfirm={async () => {
          if (!draftVersion) return;
          const published = await runPublish(draftVersion.id);
          setConfirmPublishOpen(false);
          if (published) setReloadKey((k) => k + 1);
        }}
        onCancel={() => setConfirmPublishOpen(false)}
      />
    </div>
  );
}
