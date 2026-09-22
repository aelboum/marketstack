// Centralized navigation configuration (UI-1 requirement: "Navigation
// configuration should be centralized so it can evolve later. Do not
// duplicate navigation definitions throughout the application.").
//
// `<Navigation>` and `<TopBar>` both render from this one list -- adding
// a module, or changing what's available vs. planned, is a one-line edit
// here, never a change to every place a nav item happens to be rendered.
//
// Restructured docs/ROADMAP.md Phase 28 (Command Center & Navigation
// Redesign): the previous shape was a flat, ungrouped list whose labels
// were literally the backend router names ("CRM", "Automation",
// "Reputation", ...) -- confirmed, by this file's own prior comment, to
// be an intentional design choice ("mirrors exactly the backend routers
// mounted in product/api/main.py"), now superseded by the Phase 28
// principle recorded in docs/ROADMAP.md: "the primary navigation is
// business-oriented rather than a direct mirror of backend routers."
//
// Every `segment` below still points at the exact same route a technical
// module always had -- **nothing was removed, renamed at the URL level,
// or rebuilt**. Only the grouping and the label a user sees changed. A
// technical module that has no real screen yet keeps `status: "planned"`
// and renders as a disabled "Coming soon" entry, exactly as before (UI-1
// scope: "Do not create fake pages behind these entries.").

export type NavItem = {
  key: string;
  label: string;
  /** Path segment under `/t/[tenantId]/...`; omitted for a planned item
   * with no route yet. May itself contain a `/` to point at an existing
   * sub-route of another module (e.g. "crm/opportunities") rather than
   * that module's own top-level page -- this is still the same real
   * screen, reached from a different, more business-relevant place in
   * the navigation; it does not duplicate or fork that screen. */
  segment?: string;
  status: "available" | "planned";
};

export type NavGroup = {
  key: string;
  /** The business question/job this group answers -- shown as the
   * group's own heading. Never a backend module name. */
  label: string;
  items: NavItem[];
};

// Each group answers one business question a non-technical owner would
// actually ask (docs/ROADMAP.md's own "Core product principle"). Every
// item's `label` is business language; every item's `segment` (where one
// exists) is an existing, real, already-shipped screen -- this file only
// re-labels and re-groups, it never invents a route.
export const NAV_GROUPS: NavGroup[] = [
  {
    key: "vandaag",
    label: "Vandaag",
    items: [{ key: "dashboard", label: "Vandaag", segment: "dashboard", status: "available" }],
  },
  {
    key: "inbox",
    label: "Inbox",
    items: [{ key: "conversations", label: "Inbox", segment: "conversations", status: "available" }],
  },
  {
    key: "klanten",
    label: "Klanten",
    items: [
      // "Overzicht," not "Klanten" again -- this item sits directly
      // under the "Klanten" group heading, so repeating the same word as
      // both the heading and the one link under it said nothing twice
      // for no reason (caught by Navigation.test.tsx).
      { key: "crm", label: "Overzicht", segment: "crm", status: "available" },
      { key: "reputation", label: "Reviews", segment: "reputation", status: "available" },
    ],
  },
  {
    key: "agenda",
    label: "Agenda",
    items: [{ key: "appointments", label: "Agenda", segment: "appointments", status: "available" }],
  },
  {
    key: "verkoop",
    label: "Verkoop",
    items: [
      // Reuses the existing CRM opportunities screen unchanged -- Verkoop
      // is a new front door onto real, already-shipped functionality, not
      // a new module (docs/ROADMAP.md Phase 28 scope: "do not rebuild
      // CRM"; "Verkoop can expose existing opportunity/pipeline/revenue
      // -related functionality").
      { key: "opportunities", label: "Verkoop", segment: "crm/opportunities", status: "available" },
    ],
  },
  {
    key: "marketing",
    label: "Marketing",
    items: [
      { key: "marketing", label: "Marketing", segment: "marketing", status: "available" },
      { key: "websites", label: "Websites", segment: "websites", status: "available" },
    ],
  },
  {
    key: "geld",
    label: "Geld",
    items: [
      // Neither has a screen yet -- Billing (Phase 13) shipped backend
      // only, and Accounting (Phase 24/25) has not started. Marked
      // "planned" honestly rather than pretending either exists
      // (docs/ROADMAP.md Phase 28 scope: "do not pretend that the
      // accounting system already exists").
      { key: "billing", label: "Facturatie", status: "planned" },
      { key: "accounting", label: "Boekhouding", status: "planned" },
    ],
  },
  {
    key: "instellingen",
    label: "Instellingen",
    items: [
      { key: "settings", label: "Instellingen", segment: "settings", status: "available" },
      // Agency-only tenant administration (managing client businesses),
      // not a "Klanten" (CRM/business-customer) concept -- kept distinct
      // so the two are never confused, and grouped under Instellingen
      // per docs/ROADMAP.md Phase 28's own "agency/platform-owner-only
      // configuration may remain separate where required by
      // authorization." Visibility of this screen for a given user is
      // decided by the backend's own authorization exactly as before
      // (per ADR-0011, never by a frontend `tenant_type`/`user_type`
      // check) -- a tenant with no clients simply sees an empty list.
      { key: "clients", label: "Klantbedrijven", segment: "clients", status: "available" },
      { key: "automation", label: "Automatisering", segment: "automation", status: "available" },
      { key: "telephony", label: "Telefonie", status: "planned" },
      { key: "ai", label: "AI-assistent", status: "planned" },
      { key: "prospecting", label: "Prospectie", status: "planned" },
    ],
  },
];

/** Flattened view of `NAV_GROUPS`, in the same order -- kept for any
 * caller that only needs "every item," not the grouping (e.g. a future
 * search-all-destinations feature). Prefer `NAV_GROUPS` for anything
 * that renders navigation. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);
