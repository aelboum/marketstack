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
import { listContacts, listOpportunities, listPipelines, listStages, type Contact } from "@/lib/api/crm";
import { listInbox } from "@/lib/api/conversations";
import { listRuns, listWorkflows, type Run } from "@/lib/api/automation";
import { parseMoney } from "@/lib/crm/money";

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

// --- Pipeline summary (dashboard, docs/ROADMAP.md dashboard-design
// integration) ------------------------------------------------------------
//
// `product/crm/routes.py` has no tenant-wide "opportunities for this
// pipeline" filter and no aggregation endpoint -- same real gap
// `loadAutomationActivity()` above already works around. This composes
// the summary from the existing, already-shipped endpoints:
// `listPipelines()` + `listStages()` (both tenant-wide, unpaginated --
// see components/crm/OpportunitiesList.tsx's own comment) and one bounded
// `listOpportunities()` page, filtered client-side to the chosen
// pipeline. `PIPELINE_OPPORTUNITY_SAMPLE_SIZE` is the backend's own
// maximum page size (`product/crm/pagination.py`), so this is the largest
// single request the existing contract allows -- a documented bound, not
// an oversight, exactly like `ATTENTION_WORKFLOW_SAMPLE_SIZE` above.

const PIPELINE_OPPORTUNITY_SAMPLE_SIZE = 100;

export type PipelineStageSummary = {
  stageId: string;
  stageName: string;
  isWon: boolean;
  isLost: boolean;
  dealCount: number;
  /** `null` when this stage has no amount to show -- either no
   * opportunity in it has a parseable amount, or every one that does is
   * in a currency other than `PipelineSummary.currency`. Never a
   * partial/incorrect cross-currency sum. */
  valueDecimal: number | null;
};

export type PipelineSummary = {
  pipelineName: string;
  /** The one currency this summary sums -- the currency of the first
   * priced opportunity found. An opportunity priced in a different
   * currency still counts toward `dealCount` but is excluded from every
   * value sum (see `PipelineStageSummary.valueDecimal`). `null` when no
   * opportunity in this pipeline has a parseable amount yet. */
  currency: string | null;
  stages: PipelineStageSummary[];
  /** Deals not yet in a won/lost stage. */
  openCount: number;
  /** `null` under the same rule as `PipelineStageSummary.valueDecimal`. */
  openValueDecimal: number | null;
};

/** `null` when the tenant has not created a pipeline yet -- a genuine
 * empty state, not an error. */
export async function loadPipelineSummary(tenantId: string): Promise<PipelineSummary | null> {
  const pipelines = await listPipelines(tenantId);
  if (pipelines.length === 0) return null;
  const pipeline = pipelines.find((p) => p.is_default) ?? pipelines[0];

  const stages = (await listStages(tenantId, pipeline.id)).slice().sort((a, b) => a.position - b.position);
  const { results: opportunities } = await listOpportunities(tenantId, {
    limit: PIPELINE_OPPORTUNITY_SAMPLE_SIZE,
  });
  const inPipeline = opportunities.filter((o) => o.pipeline_id === pipeline.id);

  let currency: string | null = null;
  for (const opportunity of inPipeline) {
    const parsed = parseMoney(opportunity.amount);
    if (parsed) {
      currency = parsed.currency;
      break;
    }
  }

  function sumValue(forOpportunities: typeof inPipeline): number | null {
    if (!currency) return null;
    const amounts = forOpportunities
      .map((o) => parseMoney(o.amount))
      .filter((money): money is { decimal: string; currency: string } => money !== null && money.currency === currency);
    if (amounts.length === 0) return null;
    return amounts.reduce((sum, money) => sum + Number(money.decimal), 0);
  }

  const stageSummaries: PipelineStageSummary[] = stages.map((stage) => {
    const stageOpportunities = inPipeline.filter((o) => o.stage_id === stage.id);
    return {
      stageId: stage.id,
      stageName: stage.name,
      isWon: stage.is_won,
      isLost: stage.is_lost,
      dealCount: stageOpportunities.length,
      valueDecimal: sumValue(stageOpportunities),
    };
  });

  const openOpportunities = inPipeline.filter((o) => {
    const stage = stages.find((s) => s.id === o.stage_id);
    return stage ? !stage.is_won && !stage.is_lost : true;
  });

  return {
    pipelineName: pipeline.name,
    currency,
    stages: stageSummaries,
    openCount: openOpportunities.length,
    openValueDecimal: sumValue(openOpportunities),
  };
}

// --- Dashboard KPI strip --------------------------------------------------
//
// Composes only real, already-shipped data -- see each field's own
// source below. No field is ever a placeholder: a KPI this tenant
// genuinely has no data for yet is `null`/`0`, presented by the KPI
// component as an honest "no data" state, never a fabricated number.

export type DashboardKpis = {
  /** From `loadPipelineSummary()`'s `openCount` -- `null` when the
   * tenant has no pipeline yet. */
  openOpportunities: number | null;
  /** From `loadPipelineSummary()`'s `openValueDecimal`/`currency`. */
  pipelineValueDecimal: number | null;
  pipelineCurrency: string | null;
  /** Same bounded page `loadTodaysAppointments()` itself already shows
   * in the Appointments widget -- reused here, not refetched with a
   * different limit, so the KPI number and the widget list never
   * disagree. */
  appointmentsToday: number;
  /** `listInbox(needs_reply: true)` -- the same real query
   * `components/today/AttentionSection.tsx`'s own `NeedsReplyLine`
   * already uses. */
  unreadConversations: number;
};

export async function loadDashboardKpis(tenantId: string): Promise<DashboardKpis> {
  const [pipeline, appointments, unread] = await Promise.all([
    loadPipelineSummary(tenantId),
    loadTodaysAppointments(tenantId),
    listInbox(tenantId, { needs_reply: true }),
  ]);

  return {
    openOpportunities: pipeline ? pipeline.openCount : null,
    pipelineValueDecimal: pipeline ? pipeline.openValueDecimal : null,
    pipelineCurrency: pipeline ? pipeline.currency : null,
    appointmentsToday: appointments.length,
    unreadConversations: unread.length,
  };
}
