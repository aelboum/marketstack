// Read-only composition layer for the "Vandaag" Command Center
// (docs/ROADMAP.md Phase 28). Every function here composes existing,
// already-shipped API contracts (CRM, Appointments, Automation) --
// nothing here calls a new backend aggregation endpoint, per Phase 28's
// own "prefer existing APIs" rule. The one genuine backend gap this
// phase found and fixed at its source (no authenticated way to list
// appointments at all) lives in `product/appointments/` itself, not
// here -- this file only calls the now-real `listAppointments()`.
//
// Deliberately no fabricated data anywhere below: every function either
// returns real API results or an empty array/list -- never a
// placeholder count, never a synthetic row.
import { listAppointments, type Appointment } from "@/lib/api/appointments";
import { listContacts, type Contact } from "@/lib/api/crm";
import { listRuns, listWorkflows, type Run } from "@/lib/api/automation";

/** Local-timezone "today," expressed as the UTC instants a caller needs
 * for `listAppointments()`'s `starts_after`/`starts_before` bounds --
 * computed from the browser's own local midnight, not a hardcoded
 * timezone, so "today" means the viewer's actual today. */
export function todayBounds(now: Date = new Date()): { startsAfter: string; startsBefore: string } {
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfNextDay = new Date(startOfDay);
  startOfNextDay.setDate(startOfNextDay.getDate() + 1);
  return { startsAfter: startOfDay.toISOString(), startsBefore: startOfNextDay.toISOString() };
}

export function loadTodaysAppointments(tenantId: string): Promise<Appointment[]> {
  const { startsAfter, startsBefore } = todayBounds();
  return listAppointments(tenantId, {
    starts_after: startsAfter,
    starts_before: startsBefore,
    limit: 10,
  }).then((page) => page.results);
}

export function loadRecentContacts(tenantId: string): Promise<Contact[]> {
  // `listContacts()` already orders newest-first
  // (`product/crm/contacts.py::list_contacts()` -- `created_at.desc()`),
  // so this is genuinely "recently added," not an arbitrary page.
  return listContacts(tenantId, { limit: 5 }).then((page) => page.results);
}

export type RunWithWorkflow = Run & { workflowName: string };

const ATTENTION_WORKFLOW_SAMPLE_SIZE = 10;
const RUNS_PER_WORKFLOW_SAMPLE_SIZE = 5;

/** There is no tenant-wide "every run across every workflow" endpoint
 * (`product/automation/durable/routes.py` only exposes runs nested under
 * one workflow) -- composing this from a small, bounded number of
 * `listWorkflows()` + per-workflow `listRuns()` calls is a deliberate,
 * documented efficiency trade-off for a first version of this summary,
 * not an oversight: for the common case (a handful of configured
 * workflows) this is a handful of fast requests, not an unbounded fan-
 * out, and every workflow beyond the sample size simply does not
 * contribute to this summary yet rather than the page hanging on an
 * unbounded number of calls. */
export async function loadAutomationActivity(
  tenantId: string,
): Promise<{ failed: RunWithWorkflow[]; recentlyCompleted: RunWithWorkflow[] }> {
  const workflowsPage = await listWorkflows(tenantId, { limit: ATTENTION_WORKFLOW_SAMPLE_SIZE });
  const runsByWorkflow = await Promise.all(
    workflowsPage.results.map((workflow) =>
      listRuns(tenantId, workflow.id, { limit: RUNS_PER_WORKFLOW_SAMPLE_SIZE }).then((page) =>
        page.results.map((run) => ({ ...run, workflowName: workflow.name })),
      ),
    ),
  );
  const allRuns = runsByWorkflow.flat();

  const failed = allRuns
    .filter((run) => run.status === "failed")
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  const recentlyCompleted = allRuns
    .filter((run) => run.status === "completed" && run.completed_at)
    .sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? ""));

  return { failed, recentlyCompleted };
}
