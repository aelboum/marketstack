// Centralized navigation configuration (UI-1 requirement: "Navigation
// configuration should be centralized so it can evolve later. Do not
// duplicate navigation definitions throughout the application.").
//
// `<Navigation>` and `<TopBar>` both render from this one list -- adding
// a module, or changing what's available vs. planned, is a one-line edit
// here, never a change to every place a nav item happens to be rendered.

export type NavItem = {
  key: string;
  label: string;
  /** Path segment under `/t/[tenantId]/...`; omitted for a planned item
   * with no route yet. */
  segment?: string;
  status: "available" | "planned";
};

// "Available" mirrors exactly the backend routers mounted in
// product/api/main.py as of this phase (Agency/Client, CRM,
// Conversations, Marketing, Appointments -- docs/ROADMAP.md Phases 3-7,
// all checkpointed). "Planned" mirrors the remaining Backend Track
// phases (docs/ROADMAP.md Phase 8 onward) -- listed so the shell can
// show where the product is going without pretending a screen exists
// for it yet (UI-1 scope: "Do not create fake pages behind these
// entries.").
export const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", label: "Dashboard", segment: "dashboard", status: "available" },
  { key: "clients", label: "Clients", segment: "clients", status: "available" },
  { key: "crm", label: "CRM", segment: "crm", status: "available" },
  { key: "conversations", label: "Conversations", segment: "conversations", status: "available" },
  { key: "marketing", label: "Marketing", segment: "marketing", status: "available" },
  { key: "appointments", label: "Appointments", segment: "appointments", status: "available" },
  { key: "settings", label: "Settings", segment: "settings", status: "available" },
  { key: "telephony", label: "Telephony", status: "planned" },
  { key: "ai", label: "AI", status: "planned" },
  { key: "automation", label: "Automation", segment: "automation", status: "available" },
  { key: "websites", label: "Websites", segment: "websites", status: "available" },
  { key: "reputation", label: "Reputation", segment: "reputation", status: "available" },
  { key: "billing", label: "Billing", status: "planned" },
  { key: "accounting", label: "Accounting", status: "planned" },
  { key: "prospecting", label: "Prospecting", status: "planned" },
];
