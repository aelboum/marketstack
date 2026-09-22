// Typed API functions for the Phase 4 CRM backend (`product/crm/routes.py`,
// mounted at `/v1/crm`), built on the UI-1 `request()` foundation
// (lib/api/client.ts) -- mirrors lib/api/agency.ts's own pattern; UI-3
// adds no second HTTP client. Every shape below is read directly off
// that router's own `_xxx_dict()` response builders and request models,
// not guessed from a schema.
//
// Pagination: every list endpoint takes `limit`/`offset`
// (`product/crm/pagination.py`: default 25, max 100, clamped
// server-side) and returns a plain JSON array -- no total count, no
// envelope. `hasMore` below is therefore a heuristic (`results.length
// === limit`), not an authoritative count; callers must not present it
// as an exact total.
//
// Non-enumeration: every 403/404 the backend can return for these
// routes is the identical shape `lib/api/client.ts`'s `ApiError` already
// classifies as `"forbidden"` -- nothing CRM-specific needed here.

import { request } from "@/lib/api/client";
import { API_BASE_URL } from "@/lib/api/config";
import { ApiError, classifyErrorStatus } from "@/lib/api/errors";

export type Company = {
  id: string;
  tenant_id: string;
  name: string;
  domain: string | null;
  phone: string | null;
  created_at: string;
  updated_at: string;
};

export type Contact = {
  id: string;
  tenant_id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  company_id: string | null;
  created_at: string;
  updated_at: string;
};

export type Opportunity = {
  id: string;
  tenant_id: string;
  name: string;
  contact_id: string | null;
  company_id: string | null;
  pipeline_id: string;
  stage_id: string;
  /** docs/ROADMAP.md Phase 22. `null` means unassigned -- the state
   * every opportunity is already in before this phase. */
  assigned_user_id: string | null;
  /** `"<decimal> <CURRENCY>"` (e.g. `"1500.00 USD"`), or `null` -- see
   * lib/crm/money.ts for parsing/formatting. */
  amount: string | null;
  created_at: string;
  updated_at: string;
};

export type Pipeline = {
  id: string;
  tenant_id: string;
  name: string;
  is_default: boolean;
  created_at: string;
};

export type Stage = {
  id: string;
  pipeline_id: string;
  name: string;
  position: number;
  is_won: boolean;
  is_lost: boolean;
};

export type EntityType = "contact" | "company" | "opportunity";

export type TaskActivity = {
  id: string;
  tenant_id: string;
  kind: "task";
  contact_id: string | null;
  company_id: string | null;
  opportunity_id: string | null;
  created_at: string;
  updated_at: string;
  title: string;
  description: string | null;
  due_at: string | null;
  completed_at: string | null;
};

export type NoteActivity = {
  id: string;
  tenant_id: string;
  kind: "note";
  contact_id: string | null;
  company_id: string | null;
  opportunity_id: string | null;
  created_at: string;
  updated_at: string;
  body: string;
};

export type Activity = TaskActivity | NoteActivity;

export type FieldType = "text" | "number" | "date" | "boolean";

export type FieldDefinition = {
  id: string;
  tenant_id: string;
  entity_type: EntityType;
  name: string;
  field_type: FieldType;
  created_at: string;
};

export type FieldValue = {
  id: string;
  field_definition_id: string;
  entity_type: EntityType;
  entity_id: string;
  value: string | number | boolean | null;
};

export type Tag = {
  id: string;
  tenant_id: string;
  name: string;
  created_at: string;
};

export type ImportJob = {
  id: string;
  tenant_id: string;
  status: string;
  total_rows: number | null;
  succeeded_rows: number;
  failed_rows: number;
  error_report: unknown;
  created_at: string;
  completed_at: string | null;
};

export type ListParams = {
  limit?: number;
  offset?: number;
  q?: string;
  tag?: string;
};

export type ListResult<T> = {
  results: T[];
  /** Heuristic only -- see module docstring. */
  hasMore: boolean;
};

function toListResult<T>(results: T[], limit: number): ListResult<T> {
  return { results, hasMore: results.length === limit };
}

function listQuery(params: ListParams) {
  return {
    limit: params.limit,
    offset: params.offset,
    q: params.q || undefined,
    tag: params.tag || undefined,
  };
}

// --- Companies --------------------------------------------------------

export function listCompanies(tenantId: string, params: ListParams = {}): Promise<ListResult<Company>> {
  const limit = params.limit ?? 25;
  return request<Company[]>(`/v1/crm/tenants/${tenantId}/companies`, {
    query: { ...listQuery(params), limit },
  }).then((results) => toListResult(results, limit));
}

export function getCompany(tenantId: string, companyId: string): Promise<Company> {
  return request<Company>(`/v1/crm/tenants/${tenantId}/companies/${companyId}`);
}

export function createCompany(
  tenantId: string,
  input: { name: string; domain?: string | null; phone?: string | null },
): Promise<Company> {
  return request<Company>(`/v1/crm/tenants/${tenantId}/companies`, { method: "POST", body: input });
}

export function updateCompany(
  tenantId: string,
  companyId: string,
  input: { name?: string | null; domain?: string | null; phone?: string | null },
): Promise<Company> {
  return request<Company>(`/v1/crm/tenants/${tenantId}/companies/${companyId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteCompany(tenantId: string, companyId: string): Promise<void> {
  return request<void>(`/v1/crm/tenants/${tenantId}/companies/${companyId}`, { method: "DELETE" });
}

// --- Contacts -----------------------------------------------------------

export function listContacts(tenantId: string, params: ListParams = {}): Promise<ListResult<Contact>> {
  const limit = params.limit ?? 25;
  return request<Contact[]>(`/v1/crm/tenants/${tenantId}/contacts`, {
    query: { ...listQuery(params), limit },
  }).then((results) => toListResult(results, limit));
}

export function getContact(tenantId: string, contactId: string): Promise<Contact> {
  return request<Contact>(`/v1/crm/tenants/${tenantId}/contacts/${contactId}`);
}

export function createContact(
  tenantId: string,
  input: {
    first_name: string;
    last_name: string;
    email?: string | null;
    phone?: string | null;
    company_id?: string | null;
  },
): Promise<Contact> {
  return request<Contact>(`/v1/crm/tenants/${tenantId}/contacts`, { method: "POST", body: input });
}

export function updateContact(
  tenantId: string,
  contactId: string,
  input: {
    first_name?: string | null;
    last_name?: string | null;
    email?: string | null;
    phone?: string | null;
    company_id?: string | null;
  },
): Promise<Contact> {
  return request<Contact>(`/v1/crm/tenants/${tenantId}/contacts/${contactId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteContact(tenantId: string, contactId: string): Promise<void> {
  return request<void>(`/v1/crm/tenants/${tenantId}/contacts/${contactId}`, { method: "DELETE" });
}

// --- Pipelines / stages ---------------------------------------------------

export function listPipelines(tenantId: string): Promise<Pipeline[]> {
  return request<Pipeline[]>(`/v1/crm/tenants/${tenantId}/pipelines`);
}

export function createPipeline(
  tenantId: string,
  input: { name: string; is_default?: boolean },
): Promise<Pipeline> {
  return request<Pipeline>(`/v1/crm/tenants/${tenantId}/pipelines`, { method: "POST", body: input });
}

export function listStages(tenantId: string, pipelineId: string): Promise<Stage[]> {
  return request<Stage[]>(`/v1/crm/tenants/${tenantId}/pipelines/${pipelineId}/stages`);
}

export function createStage(
  tenantId: string,
  pipelineId: string,
  input: { name: string; position: number; is_won?: boolean; is_lost?: boolean },
): Promise<Stage> {
  return request<Stage>(`/v1/crm/tenants/${tenantId}/pipelines/${pipelineId}/stages`, {
    method: "POST",
    body: input,
  });
}

// --- Opportunities -------------------------------------------------------

export function listOpportunities(
  tenantId: string,
  params: ListParams = {},
): Promise<ListResult<Opportunity>> {
  const limit = params.limit ?? 25;
  return request<Opportunity[]>(`/v1/crm/tenants/${tenantId}/opportunities`, {
    query: { ...listQuery(params), limit },
  }).then((results) => toListResult(results, limit));
}

export function getOpportunity(tenantId: string, opportunityId: string): Promise<Opportunity> {
  return request<Opportunity>(`/v1/crm/tenants/${tenantId}/opportunities/${opportunityId}`);
}

export type OpportunityInput = {
  name: string;
  pipeline_id: string;
  stage_id: string;
  contact_id?: string | null;
  company_id?: string | null;
  amount_decimal?: string | null;
  amount_currency?: string | null;
};

export function createOpportunity(tenantId: string, input: OpportunityInput): Promise<Opportunity> {
  return request<Opportunity>(`/v1/crm/tenants/${tenantId}/opportunities`, {
    method: "POST",
    body: input,
  });
}

export function updateOpportunity(
  tenantId: string,
  opportunityId: string,
  input: { name?: string | null; amount_decimal?: string | null; amount_currency?: string | null },
): Promise<Opportunity> {
  return request<Opportunity>(`/v1/crm/tenants/${tenantId}/opportunities/${opportunityId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteOpportunity(tenantId: string, opportunityId: string): Promise<void> {
  return request<void>(`/v1/crm/tenants/${tenantId}/opportunities/${opportunityId}`, {
    method: "DELETE",
  });
}

export function changeOpportunityStage(
  tenantId: string,
  opportunityId: string,
  stageId: string,
): Promise<Opportunity> {
  return request<Opportunity>(`/v1/crm/tenants/${tenantId}/opportunities/${opportunityId}/stage`, {
    method: "POST",
    body: { stage_id: stageId },
  });
}

export function assignOpportunity(
  tenantId: string,
  opportunityId: string,
  assignedUserId: string | null,
): Promise<Opportunity> {
  return request<Opportunity>(`/v1/crm/tenants/${tenantId}/opportunities/${opportunityId}/assign`, {
    method: "POST",
    body: { assigned_user_id: assignedUserId },
  });
}

// --- Tasks / notes / activities -------------------------------------------

export type ActivityParent =
  | { contactId: string }
  | { companyId: string }
  | { opportunityId: string };

function parentSegment(parent: ActivityParent): string {
  if ("contactId" in parent) return `contacts/${parent.contactId}`;
  if ("companyId" in parent) return `companies/${parent.companyId}`;
  return `opportunities/${parent.opportunityId}`;
}

export function listActivities(
  tenantId: string,
  parent: ActivityParent,
  params: { limit?: number; offset?: number } = {},
): Promise<Activity[]> {
  return request<Activity[]>(`/v1/crm/tenants/${tenantId}/${parentSegment(parent)}/activities`, {
    query: params,
  });
}

export function createTask(
  tenantId: string,
  parent: ActivityParent,
  input: { title: string; description?: string | null; due_at?: string | null },
): Promise<TaskActivity> {
  return request<TaskActivity>(`/v1/crm/tenants/${tenantId}/${parentSegment(parent)}/tasks`, {
    method: "POST",
    body: input,
  });
}

export function completeTask(
  tenantId: string,
  taskId: string,
  completedAt?: string,
): Promise<TaskActivity> {
  return request<TaskActivity>(`/v1/crm/tenants/${tenantId}/tasks/${taskId}/complete`, {
    method: "POST",
    body: { completed_at: completedAt ?? null },
  });
}

export function deleteTask(tenantId: string, taskId: string): Promise<void> {
  return request<void>(`/v1/crm/tenants/${tenantId}/tasks/${taskId}`, { method: "DELETE" });
}

export function createNote(
  tenantId: string,
  parent: ActivityParent,
  body: string,
): Promise<NoteActivity> {
  return request<NoteActivity>(`/v1/crm/tenants/${tenantId}/${parentSegment(parent)}/notes`, {
    method: "POST",
    body: { body },
  });
}

export function deleteNote(tenantId: string, noteId: string): Promise<void> {
  return request<void>(`/v1/crm/tenants/${tenantId}/notes/${noteId}`, { method: "DELETE" });
}

// --- Custom fields (Phase 4.4) --------------------------------------------

export function listFieldDefinitions(
  tenantId: string,
  entityType: EntityType,
): Promise<FieldDefinition[]> {
  return request<FieldDefinition[]>(`/v1/crm/tenants/${tenantId}/custom-fields`, {
    query: { entity_type: entityType },
  });
}

export function defineField(
  tenantId: string,
  input: { entity_type: EntityType; name: string; field_type: FieldType },
): Promise<FieldDefinition> {
  return request<FieldDefinition>(`/v1/crm/tenants/${tenantId}/custom-fields`, {
    method: "POST",
    body: input,
  });
}

export function getFieldValues(
  tenantId: string,
  entityType: EntityType,
  entityId: string,
): Promise<FieldValue[]> {
  return request<FieldValue[]>(
    `/v1/crm/tenants/${tenantId}/${entityType}/${entityId}/custom-fields`,
  );
}

export function setFieldValue(
  tenantId: string,
  entityType: EntityType,
  entityId: string,
  fieldDefinitionId: string,
  value: string | number | boolean,
): Promise<FieldValue> {
  return request<FieldValue>(`/v1/crm/tenants/${tenantId}/${entityType}/${entityId}/custom-fields`, {
    method: "PUT",
    body: { field_definition_id: fieldDefinitionId, value },
  });
}

// --- Tags ------------------------------------------------------------------

export function listTags(tenantId: string): Promise<Tag[]> {
  return request<Tag[]>(`/v1/crm/tenants/${tenantId}/tags`);
}

export function createTag(tenantId: string, name: string): Promise<Tag> {
  return request<Tag>(`/v1/crm/tenants/${tenantId}/tags`, { method: "POST", body: { name } });
}

export function listTagsForEntity(
  tenantId: string,
  entityType: EntityType,
  entityId: string,
): Promise<Tag[]> {
  return request<Tag[]>(`/v1/crm/tenants/${tenantId}/${entityType}/${entityId}/tags`);
}

export function attachTag(
  tenantId: string,
  entityType: EntityType,
  entityId: string,
  tagId: string,
): Promise<void> {
  return request<void>(`/v1/crm/tenants/${tenantId}/${entityType}/${entityId}/tags`, {
    method: "POST",
    body: { tag_id: tagId },
  });
}

export function detachTag(
  tenantId: string,
  entityType: EntityType,
  entityId: string,
  tagId: string,
): Promise<void> {
  return request<void>(`/v1/crm/tenants/${tenantId}/${entityType}/${entityId}/tags/${tagId}`, {
    method: "DELETE",
  });
}

// --- Import / export (Phase 4.5) -------------------------------------------

export function importContacts(tenantId: string, csvContent: string): Promise<ImportJob> {
  return request<ImportJob>(`/v1/crm/tenants/${tenantId}/contact-imports`, {
    method: "POST",
    body: { csv_content: csvContent },
  });
}

export function getImportJob(tenantId: string, importJobId: string): Promise<ImportJob> {
  return request<ImportJob>(`/v1/crm/tenants/${tenantId}/imports/${importJobId}`);
}

/** The export route returns `text/csv` directly (not JSON) -- bypasses
 * `request()`'s JSON parsing and reuses its own credentialed-fetch/error
 * handling instead, since this is the one CRM response that is not JSON. */
export async function exportContactsCsv(tenantId: string): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/v1/crm/tenants/${tenantId}/contact-exports`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(classifyErrorStatus(response.status), "Could not export contacts.", {
      status: response.status,
    });
  }
  return response.text();
}
