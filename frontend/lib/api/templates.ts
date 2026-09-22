// Typed API functions for the Phase 14 Templates/Snapshots backend
// (`product/templates/routes.py`, mounted at `/v1/templates`), built on
// UI-1's `request()` foundation. First frontend consumer of this router
// (docs/ROADMAP.md Phase 21: "Business Setup," agency-only) -- exposes
// only `listSnapshots()`, the one read this phase's own provisioning UI
// needs. This module does not add a snapshot-authoring UI (creating one
// remains an API-only capability today); it only lets an agency choose
// among the setups it already has.

import { request } from "@/lib/api/client";

export type Snapshot = {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  schema_version: number;
  included_domains: string[];
  created_by_user_id: string;
  created_at: string;
};

export function listSnapshots(tenantId: string): Promise<Snapshot[]> {
  return request<Snapshot[]>(`/v1/templates/tenants/${tenantId}/snapshots`);
}
