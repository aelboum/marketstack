// Typed API functions for the Phase 5 Conversations backend
// (`product/conversations/routes.py`, mounted at `/v1/conversations`),
// built on the UI-1 `request()` foundation -- mirrors lib/api/agency.ts
// and lib/api/crm.ts; UI-4 adds no second HTTP client. Every shape below
// is read directly off that router's own `_xxx_dict()` builders and
// request models.
//
// `GET .../threads` still takes only `limit`/`offset` (no filter/search)
// -- the Unified Inbox (docs/ROADMAP.md Phase 30) uses the newer
// `GET .../inbox` below instead, which does support `assigned`/
// `channel`/`needs_reply` filters alongside each thread's latest-message
// summary. Deliberately still absent from both: full-text search, a
// date filter -- no existing capability provides either.

import { request } from "@/lib/api/client";

export type Channel = "email" | "sms" | "whatsapp" | "chat";
export const CHANNELS: Channel[] = ["email", "sms", "whatsapp", "chat"];

export type Direction = "inbound" | "outbound";

export type Thread = {
  id: string;
  tenant_id: string;
  contact_id: string | null;
  channel: Channel;
  assigned_to_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: string;
  tenant_id: string;
  thread_id: string;
  direction: Direction;
  is_internal_note: boolean;
  /** Bounded server-side to 10,000 chars
   * (`product/conversations/models.py::MAX_MESSAGE_BODY_LENGTH`). */
  body: string;
  author_user_id: string | null;
  sequence: number;
  created_at: string;
};

export type Template = {
  id: string;
  tenant_id: string;
  name: string;
  channel: Channel | null;
  body: string;
  created_at: string;
  updated_at: string;
};

export const MAX_MESSAGE_BODY_LENGTH = 10_000;

export type Page<T> = {
  results: T[];
  /** Heuristic only (`results.length === limit`) -- the backend returns
   * a plain array, no total count. */
  hasMore: boolean;
};

function toPage<T>(results: T[], limit: number): Page<T> {
  return { results, hasMore: results.length === limit };
}

// --- Threads ---------------------------------------------------------------

export function listThreads(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Thread>> {
  const limit = params.limit ?? 25;
  return request<Thread[]>(`/v1/conversations/tenants/${tenantId}/threads`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getThread(tenantId: string, threadId: string): Promise<Thread> {
  return request<Thread>(`/v1/conversations/tenants/${tenantId}/threads/${threadId}`);
}

export function createThread(
  tenantId: string,
  input: { contact_id: string; channel: Channel },
): Promise<Thread> {
  return request<Thread>(`/v1/conversations/tenants/${tenantId}/threads`, {
    method: "POST",
    body: input,
  });
}

export function updateThreadChannel(
  tenantId: string,
  threadId: string,
  channel: Channel,
): Promise<Thread> {
  return request<Thread>(`/v1/conversations/tenants/${tenantId}/threads/${threadId}`, {
    method: "PATCH",
    body: { channel },
  });
}

export function deleteThread(tenantId: string, threadId: string): Promise<void> {
  return request<void>(`/v1/conversations/tenants/${tenantId}/threads/${threadId}`, {
    method: "DELETE",
  });
}

export function assignThread(
  tenantId: string,
  threadId: string,
  assigneeUserId: string,
): Promise<Thread> {
  return request<Thread>(`/v1/conversations/tenants/${tenantId}/threads/${threadId}/assign`, {
    method: "POST",
    body: { assignee_user_id: assigneeUserId },
  });
}

// --- Unified Inbox (docs/ROADMAP.md Phase 30) -------------------------

export type InboxItem = {
  thread_id: string;
  tenant_id: string;
  contact_id: string | null;
  channel: Channel;
  assigned_to_user_id: string | null;
  created_at: string;
  updated_at: string;
  /** `null` for a thread with no messages yet -- a real, empty
   * conversation, not missing data. */
  last_message_preview: string | null;
  last_message_at: string | null;
  last_message_direction: Direction | null;
  last_message_is_internal_note: boolean | null;
  /** Derived server-side from the latest message's own direction --
   * never a persisted "unread" flag, because this schema has none
   * (`product/conversations/inbox.py`'s own module docstring). `true`
   * means the customer's last message has no reply yet. */
  needs_reply: boolean;
};

export type AssignedFilter = "me" | "unassigned";

export function listInbox(
  tenantId: string,
  params: {
    assigned?: AssignedFilter;
    channel?: Channel;
    needs_reply?: boolean;
    limit?: number;
    offset?: number;
  } = {},
): Promise<InboxItem[]> {
  return request<InboxItem[]>(`/v1/conversations/tenants/${tenantId}/inbox`, {
    query: {
      assigned: params.assigned,
      channel: params.channel,
      needs_reply: params.needs_reply,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

// --- Messages ----------------------------------------------------------

export function listMessages(
  tenantId: string,
  threadId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Message>> {
  const limit = params.limit ?? 25;
  return request<Message[]>(
    `/v1/conversations/tenants/${tenantId}/threads/${threadId}/messages`,
    { query: { limit, offset: params.offset ?? 0 } },
  ).then((results) => toPage(results, limit));
}

/**
 * Logs an internal note or a manually-recorded message -- this does
 * **not** deliver anything to the contact through any provider (see
 * `product/conversations/messages.py::create_message()`'s own
 * docstring: it only ever inserts a row, never calls a provider). Real
 * delivery exists only for email, via `sendEmail()` below.
 */
export function createMessage(
  tenantId: string,
  threadId: string,
  input: { direction: Direction; is_internal_note: boolean; body: string },
): Promise<Message> {
  return request<Message>(
    `/v1/conversations/tenants/${tenantId}/threads/${threadId}/messages`,
    { method: "POST", body: input },
  );
}

/**
 * The one real "send" operation this API exposes -- actually calls
 * `core.email.send_email()` server-side and only records the message on
 * success (`product/conversations/email_sending.py`'s own docstring: "On
 * provider failure, no message is recorded"). There is no equivalent
 * send-sms/send-whatsapp route.
 */
export function sendEmail(
  tenantId: string,
  threadId: string,
  input: { to_email: string; subject: string; body: string },
): Promise<Message> {
  return request<Message>(
    `/v1/conversations/tenants/${tenantId}/threads/${threadId}/send-email`,
    { method: "POST", body: input },
  );
}

// --- Templates ---------------------------------------------------------

export function listTemplates(tenantId: string): Promise<Template[]> {
  return request<Template[]>(`/v1/conversations/tenants/${tenantId}/templates`);
}

export function getTemplate(tenantId: string, templateId: string): Promise<Template> {
  return request<Template>(`/v1/conversations/tenants/${tenantId}/templates/${templateId}`);
}

export function createTemplate(
  tenantId: string,
  input: { name: string; body: string; channel?: Channel | null },
): Promise<Template> {
  return request<Template>(`/v1/conversations/tenants/${tenantId}/templates`, {
    method: "POST",
    body: input,
  });
}

export function updateTemplate(
  tenantId: string,
  templateId: string,
  input: { body?: string | null; channel?: Channel | null },
): Promise<Template> {
  return request<Template>(`/v1/conversations/tenants/${tenantId}/templates/${templateId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteTemplate(tenantId: string, templateId: string): Promise<void> {
  return request<void>(`/v1/conversations/tenants/${tenantId}/templates/${templateId}`, {
    method: "DELETE",
  });
}
