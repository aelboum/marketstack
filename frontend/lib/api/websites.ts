// Typed API functions for the Phase 11.1 Websites backend
// (`product/websites/routes.py`, prefix `/v1/websites`), built on the
// UI-1 `request()` foundation -- UI-12 adds no second HTTP client.
//
// Unlike Reputation (UI-11), this router is already fully wired in
// `product/api/main.py` -- mounted, purge-participant registered, and
// its `agency.role_provisioned` event handler imported -- so there is no
// deferred-mount caveat here.
//
// Deliberately absent, because the backend has none:
//   - no page builder/CMS beyond the closed, five-type block vocabulary
//     (`product/websites/content_blocks.py::BLOCK_TYPES`) -- no raw
//     HTML block, no rich-text block, no custom component block;
//   - no asset upload -- `image.asset_ref` is a bounded identifier
//     string only, not backed by a real upload flow yet
//     (`content_blocks.py`'s own module docstring);
//   - no DNS/TLS/domain-registrar automation -- `custom_domain` is a
//     bounded, globally-unique string field only
//     (`product/websites/models.py::Website`'s own module docstring);
//   - no "archived"/"scheduled" page status -- exactly two states,
//     `draft`/`published` (`product/websites/pages.py`'s own module
//     docstring);
//   - no search/filter on either list endpoint -- `limit`/`offset` only;
//   - no public-page-render client here -- `GET /v1/websites/public/
//     {website_slug}/{page_slug}` is unauthenticated and meant for a
//     separate public renderer, not this authenticated tenant dashboard.
//
// Named `WebsitePage`, not `Page` -- this module's own `Page<T>`
// pagination wrapper (the same shape every other `lib/api/*.ts` client
// uses) would otherwise collide with the backend's own `Page` resource
// name in this one file.

import { request } from "@/lib/api/client";

export type Website = {
  id: string;
  tenant_id: string;
  slug: string;
  name: string;
  custom_domain: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};

export type WebsitePageStatus = "draft" | "published";

/** `product/websites/content_blocks.py::BLOCK_TYPES`. */
export type ContentBlock =
  | { type: "heading"; text: string; level?: number }
  | { type: "paragraph"; text: string }
  | { type: "image"; asset_ref: string; alt_text?: string | null }
  | { type: "button"; text: string; url: string }
  | { type: "spacer" };

export const BLOCK_TYPES: ContentBlock["type"][] = [
  "heading",
  "paragraph",
  "image",
  "button",
  "spacer",
];

export type WebsitePage = {
  id: string;
  tenant_id: string;
  website_id: string;
  slug: string;
  title: string;
  status: WebsitePageStatus;
  content_blocks: ContentBlock[];
  published_at: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};

export type Page<T> = {
  results: T[];
  /** Heuristic only (`results.length === limit`) -- every list endpoint
   * here returns a plain array, never a total count. */
  hasMore: boolean;
};

function toPage<T>(results: T[], limit: number): Page<T> {
  return { results, hasMore: results.length === limit };
}

/** `product/websites/pagination.py::DEFAULT_PAGE_SIZE`. */
const DEFAULT_LIMIT = 25;

// --- Websites --------------------------------------------------------------

export type CreateWebsiteInput = {
  slug: string;
  name: string;
  custom_domain?: string | null;
};

export function createWebsite(tenantId: string, input: CreateWebsiteInput): Promise<Website> {
  return request<Website>(`/v1/websites/tenants/${tenantId}/websites`, {
    method: "POST",
    body: input,
  });
}

export function listWebsites(
  tenantId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<Website>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<Website[]>(`/v1/websites/tenants/${tenantId}/websites`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getWebsite(tenantId: string, websiteId: string): Promise<Website> {
  return request<Website>(`/v1/websites/tenants/${tenantId}/websites/${websiteId}`);
}

export type UpdateWebsiteInput = {
  name?: string | null;
  custom_domain?: string | null;
  /** Disambiguates "omitted" from "explicit null" at the HTTP layer,
   * mirroring `product/websites/routes.py::UpdateWebsiteRequest`'s own
   * `clear_custom_domain` field -- a JSON body cannot otherwise carry
   * "field sent as null" separately from "field not sent". */
  clear_custom_domain?: boolean;
};

export function updateWebsite(
  tenantId: string,
  websiteId: string,
  input: UpdateWebsiteInput,
): Promise<Website> {
  return request<Website>(`/v1/websites/tenants/${tenantId}/websites/${websiteId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deleteWebsite(tenantId: string, websiteId: string): Promise<void> {
  return request<void>(`/v1/websites/tenants/${tenantId}/websites/${websiteId}`, {
    method: "DELETE",
  });
}

// --- Pages -------------------------------------------------------------------

export type CreatePageInput = {
  slug: string;
  title: string;
  content_blocks?: ContentBlock[];
};

export function createPage(
  tenantId: string,
  websiteId: string,
  input: CreatePageInput,
): Promise<WebsitePage> {
  return request<WebsitePage>(`/v1/websites/tenants/${tenantId}/websites/${websiteId}/pages`, {
    method: "POST",
    body: input,
  });
}

export function listPages(
  tenantId: string,
  websiteId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<Page<WebsitePage>> {
  const limit = params.limit ?? DEFAULT_LIMIT;
  return request<WebsitePage[]>(`/v1/websites/tenants/${tenantId}/websites/${websiteId}/pages`, {
    query: { limit, offset: params.offset ?? 0 },
  }).then((results) => toPage(results, limit));
}

export function getPage(tenantId: string, pageId: string): Promise<WebsitePage> {
  return request<WebsitePage>(`/v1/websites/tenants/${tenantId}/pages/${pageId}`);
}

export type UpdatePageInput = {
  title?: string | null;
  content_blocks?: ContentBlock[] | null;
};

/** `PATCH .../pages/{id}`. Only ever touches draft state -- never the
 * published snapshot, which only `publishPage()` writes
 * (`product/websites/pages.py`'s own module docstring). */
export function updatePage(
  tenantId: string,
  pageId: string,
  input: UpdatePageInput,
): Promise<WebsitePage> {
  return request<WebsitePage>(`/v1/websites/tenants/${tenantId}/pages/${pageId}`, {
    method: "PATCH",
    body: input,
  });
}

export function deletePage(tenantId: string, pageId: string): Promise<void> {
  return request<void>(`/v1/websites/tenants/${tenantId}/pages/${pageId}`, { method: "DELETE" });
}

/** Copies the current draft `content_blocks` into the public snapshot
 * and moves `status` to `published`. */
export function publishPage(tenantId: string, pageId: string): Promise<WebsitePage> {
  return request<WebsitePage>(`/v1/websites/tenants/${tenantId}/pages/${pageId}/publish`, {
    method: "POST",
  });
}

/** Moves `status` back to `draft`. Does NOT discard the last published
 * snapshot -- only a follow-up `publishPage()` overwrites it. */
export function unpublishPage(tenantId: string, pageId: string): Promise<WebsitePage> {
  return request<WebsitePage>(`/v1/websites/tenants/${tenantId}/pages/${pageId}/unpublish`, {
    method: "POST",
  });
}
