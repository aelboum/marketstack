// Typed API functions for the Phase 6 Marketing backend
// (`product/marketing/routes.py`, mounted at `/v1/marketing`), built on
// the UI-1 `request()` foundation -- mirrors lib/api/{agency,crm,
// conversations}.ts; UI-5 adds no second HTTP client. Every shape below
// is read directly off that router's own `_xxx_dict()` builders and
// request models.
//
// Deliberately absent, because the backend has none:
//   - no campaign metrics/aggregate KPI endpoint (open/click *counts*)
//     -- only two public, write-only tracking pixels/redirects exist
//     (`GET /track/open/{token}`, `GET /track/click/{token}`), neither
//     readable by this app;
//   - no form *edit* endpoint (create/list/get/delete only);
//   - no way to edit a campaign's audience segmentation after creation
//     (`UpdateCampaignRequest` has no segment_q/segment_tag/
//     segment_custom_field field, even though the service layer
//     technically could -- the route does not expose it, and the route
//     is the real contract);
//   - no campaign channel update (channel is create-only).
// See this phase's own report for the full gap list.

import { request } from "@/lib/api/client";

export type Channel = "email" | "sms";
export const CHANNELS: Channel[] = ["email", "sms"];

export type CampaignStatus = "draft" | "sending" | "sent" | "cancelled" | "failed";
export type RecipientStatus = "pending" | "sent" | "suppressed" | "failed";
export type SuppressionReason = "unsubscribed" | "bounced" | "complained" | "manual";
export const SUPPRESSION_REASONS: SuppressionReason[] = [
  "unsubscribed",
  "bounced",
  "complained",
  "manual",
];

export type TemplateType = "email_campaign" | "sms_campaign" | "landing_page";
export const TEMPLATE_TYPES: TemplateType[] = ["email_campaign", "sms_campaign", "landing_page"];

export type FormFieldType = "text" | "email" | "phone";
export const FORM_FIELD_TYPES: FormFieldType[] = ["text", "email", "phone"];

export type Campaign = {
  id: string;
  tenant_id: string;
  name: string;
  channel: Channel;
  status: CampaignStatus;
  subject: string | null;
  body: string;
  /** A server-serialized description of the audience filter this
   * campaign was created with -- opaque display text, not a re-editable
   * structured value (see module docstring: the update route has no
   * segmentation fields at all). */
  segment_query: string;
  template_id: string | null;
  click_target_url: string | null;
  created_at: string;
  updated_at: string;
};

export type CampaignRecipient = {
  id: string;
  campaign_id: string;
  contact_id: string | null;
  status: RecipientStatus;
  sent_at: string | null;
  error: string | null;
};

export type Suppression = {
  id: string;
  tenant_id: string;
  contact_id: string;
  channel: Channel;
  reason: SuppressionReason;
  created_at: string;
};

export type FormFieldDefinition = {
  name: string;
  field_type: FormFieldType;
  required: boolean;
};

export type MarketingForm = {
  id: string;
  tenant_id: string;
  name: string;
  /** The public submission token -- combine with the (documented, not
   * API-exposed) public submit route to build a shareable link:
   * `POST /v1/marketing/forms/{form_token}/submit`. */
  form_token: string;
  fields: FormFieldDefinition[];
  created_at: string;
  updated_at: string;
};

export type FormSubmission = {
  id: string;
  tenant_id: string;
  form_id: string;
  contact_id: string | null;
  /** Free-text values the submitter typed -- always rendered as plain
   * text, never as HTML. */
  submitted_data: Record<string, string>;
  created_at: string;
};

export type Template = {
  id: string;
  tenant_id: string;
  name: string;
  template_type: TemplateType;
  content: string;
  created_at: string;
  updated_at: string;
};

export type Page<T> = {
  results: T[];
  /** Heuristic only (`results.length === limit`) -- the backend returns
   * a plain array, no total count, for every list endpoint here. */
  hasMore: boolean;
};

function toPage<T>(results: T[], limit: number): Page<T> {
  return { results, hasMore: results.length === limit };
}

const DEFAULT_LIMIT = 25;

// --- Campaigns ---------------------------------------------------------

export function listCampaigns(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Campaign>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Campaign[]>(`/v1/marketing/tenants/${tenantId}/campaigns`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getCampaign(tenantId: string, campaignId: string): Promise<Campaign> {
  return request<Campaign>(`/v1/marketing/tenants/${tenantId}/campaigns/${campaignId}`);
}

export type CreateCampaignInput = {
  name: string;
  channel: Channel;
  body?: string;
  subject?: string | null;
  segment_q?: string | null;
  segment_tag?: string | null;
  segment_custom_field?: string[];
  template_id?: string | null;
  click_target_url?: string | null;
};

export function createCampaign(tenantId: string, input: CreateCampaignInput): Promise<Campaign> {
  return request<Campaign>(`/v1/marketing/tenants/${tenantId}/campaigns`, {
    method: "POST",
    body: input,
  });
}

export type UpdateCampaignInput = {
  name?: string | null;
  subject?: string | null;
  body?: string | null;
  template_id?: string | null;
  click_target_url?: string | null;
  update_click_target_url?: boolean;
};

export function updateCampaign(
  tenantId: string,
  campaignId: string,
  input: UpdateCampaignInput,
): Promise<Campaign> {
  return request<Campaign>(`/v1/marketing/tenants/${tenantId}/campaigns/${campaignId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteCampaign(tenantId: string, campaignId: string): Promise<void> {
  return request<void>(`/v1/marketing/tenants/${tenantId}/campaigns/${campaignId}`, {
    method: "DELETE",
  });
}

export type SendCampaignResult = {
  campaign_id: string;
  recipient_count: number;
  suppressed_count: number;
  job_id: string;
};

export function sendCampaign(tenantId: string, campaignId: string): Promise<SendCampaignResult> {
  return request<SendCampaignResult>(
    `/v1/marketing/tenants/${tenantId}/campaigns/${campaignId}/send`,
    { method: "POST" },
  );
}

export function cancelCampaign(tenantId: string, campaignId: string): Promise<Campaign> {
  return request<Campaign>(`/v1/marketing/tenants/${tenantId}/campaigns/${campaignId}/cancel`, {
    method: "POST",
  });
}

export function listCampaignRecipients(
  tenantId: string,
  campaignId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<CampaignRecipient>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<CampaignRecipient[]>(
    `/v1/marketing/tenants/${tenantId}/campaigns/${campaignId}/recipients`,
    { query: { limit, offset: params.offset ?? 0 } },
  ).then((results) => toPage(results, limit));
}

// --- Suppressions --------------------------------------------------------

export function listSuppressions(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Suppression>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Suppression[]>(`/v1/marketing/tenants/${tenantId}/suppressions`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function createSuppression(
  tenantId: string,
  input: { contact_id: string; channel: Channel; reason: SuppressionReason },
): Promise<Suppression> {
  return request<Suppression>(`/v1/marketing/tenants/${tenantId}/suppressions`, {
    method: "POST",
    body: input,
  });
}

export function deleteSuppression(tenantId: string, suppressionId: string): Promise<void> {
  return request<void>(`/v1/marketing/tenants/${tenantId}/suppressions/${suppressionId}`, {
    method: "DELETE",
  });
}

// --- Forms (authenticated management) -------------------------------------

export function listForms(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<MarketingForm>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<MarketingForm[]>(`/v1/marketing/tenants/${tenantId}/forms`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getForm(tenantId: string, formId: string): Promise<MarketingForm> {
  return request<MarketingForm>(`/v1/marketing/tenants/${tenantId}/forms/${formId}`);
}

export function createForm(
  tenantId: string,
  input: { name: string; fields: FormFieldDefinition[] },
): Promise<MarketingForm> {
  return request<MarketingForm>(`/v1/marketing/tenants/${tenantId}/forms`, {
    method: "POST",
    body: input,
  });
}

export function deleteForm(tenantId: string, formId: string): Promise<void> {
  return request<void>(`/v1/marketing/tenants/${tenantId}/forms/${formId}`, { method: "DELETE" });
}

export function listFormSubmissions(
  tenantId: string,
  formId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<FormSubmission>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<FormSubmission[]>(`/v1/marketing/tenants/${tenantId}/forms/${formId}/submissions`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

// --- Templates ---------------------------------------------------------

export function listTemplates(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Template>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Template[]>(`/v1/marketing/tenants/${tenantId}/templates`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getTemplate(tenantId: string, templateId: string): Promise<Template> {
  return request<Template>(`/v1/marketing/tenants/${tenantId}/templates/${templateId}`);
}

export function createTemplate(
  tenantId: string,
  input: { name: string; template_type: TemplateType; content: string },
): Promise<Template> {
  return request<Template>(`/v1/marketing/tenants/${tenantId}/templates`, {
    method: "POST",
    body: input,
  });
}

export function updateTemplate(
  tenantId: string,
  templateId: string,
  input: { name?: string | null; content?: string | null },
): Promise<Template> {
  return request<Template>(`/v1/marketing/tenants/${tenantId}/templates/${templateId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteTemplate(tenantId: string, templateId: string): Promise<void> {
  return request<void>(`/v1/marketing/tenants/${tenantId}/templates/${templateId}`, {
    method: "DELETE",
  });
}

export function cloneTemplate(
  tenantId: string,
  templateId: string,
  newName: string,
): Promise<Template> {
  return request<Template>(`/v1/marketing/tenants/${tenantId}/templates/${templateId}/clone`, {
    method: "POST",
    body: { new_name: newName },
  });
}
