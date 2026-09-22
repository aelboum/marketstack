// Centralized navigation configuration (UI-1 requirement: "Navigation
// configuration should be centralized so it can evolve later. Do not
// duplicate navigation definitions throughout the application.").
//
// `<Navigation>` and `<TopBar>` both render from this one list -- adding
// a module, or changing what's available vs. planned, is a one-line edit
// here, never a change to every place a nav item happens to be rendered.
//
// Approved IA (dashboard-design integration, navigation correction pass):
// exactly 11 primary items, in this exact order and with these exact
// labels, matching the approved mockup navigation:
//   Dashboard, Inbox, Klanten, Verkoop, Agenda, Groei, Automatiseringen,
//   Boekhouding, Reputatie, AI, Beheer
// A primary item with `children` is an organizational parent (Groei,
// Boekhouding, Beheer) or a real destination that also has a related
// sub-destination (Inbox -> Telefonie) -- `Navigation.tsx` renders
// children as an always-visible nested list under the parent, the same
// shape the old grouped nav already used, just driven by `children`
// instead of a separate `NavGroup[]` list.
//
// Real, already-shipped screens that are not one of the 11 approved
// top-level labels are reorganized as children rather than deleted --
// every route below already existed before this pass:
//   Goedkeuringen, Instellingen, Klantbedrijven -> under Beheer
//   Marketing, Websites                          -> under Groei
//   Facturatie                                    -> under Boekhouding
//   Telefonie                                     -> under Inbox
//   Prospectie                                    -> under Groei (no
//     existing route of its own either way; grouped with the other
//     growth-oriented, not-yet-built destinations)
// Nothing was removed, renamed at the URL level, or rebuilt. A
// technical capability that has no real screen yet keeps
// `status: "planned"` and renders as a disabled "Coming soon" entry
// (UI-1 scope: "Do not create fake pages behind these entries.").
//
// `labelEn`: the string shown when the header's NL/EN toggle
// (lib/i18n/locale-context.tsx) is set to English.

export type NavItem = {
  key: string;
  label: string;
  labelEn?: string;
  /** Path segment under `/t/[tenantId]/...`; omitted for a planned item
   * with no route yet, or for a pure organizational parent (Groei,
   * Boekhouding, Beheer) that is not itself a destination. May itself
   * contain a `/` to point at an existing sub-route of another module
   * (e.g. "crm/opportunities") rather than that module's own top-level
   * page -- this is still the same real screen, reached from a
   * different, more business-relevant place in the navigation; it does
   * not duplicate or fork that screen. */
  segment?: string;
  status: "available" | "planned";
  /** Sub-destinations rendered in an always-visible nested list under
   * this item. Absent (not an empty array) for a plain leaf item. */
  children?: NavItem[];
};

export const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", label: "Dashboard", labelEn: "Dashboard", segment: "dashboard", status: "available" },
  {
    key: "conversations",
    label: "Inbox",
    labelEn: "Inbox",
    segment: "conversations",
    status: "available",
    children: [
      // No existing telephony route -- kept honestly "planned" rather
      // than pointing at a fake page.
      { key: "telephony", label: "Telefonie", labelEn: "Telephony", status: "planned" },
    ],
  },
  { key: "crm", label: "Klanten", labelEn: "Customers", segment: "crm", status: "available" },
  {
    key: "opportunities",
    label: "Verkoop",
    labelEn: "Sales",
    segment: "crm/opportunities",
    status: "available",
  },
  { key: "appointments", label: "Agenda", labelEn: "Calendar", segment: "appointments", status: "available" },
  {
    // Organizational parent -- no route of its own (the approved IA
    // calls for "Groei" as a real top-level item regardless of whether
    // a single /growth landing page exists; its real children below are
    // what make it a genuine destination, not a placeholder).
    key: "growth",
    label: "Groei",
    labelEn: "Growth",
    status: "available",
    children: [
      { key: "marketing", label: "Marketing", labelEn: "Marketing", segment: "marketing", status: "available" },
      { key: "websites", label: "Websites", labelEn: "Websites", segment: "websites", status: "available" },
      // No existing prospecting route either -- honestly "planned".
      { key: "prospecting", label: "Prospectie", labelEn: "Prospecting", status: "planned" },
    ],
  },
  {
    key: "automation",
    label: "Automatiseringen",
    labelEn: "Automations",
    segment: "automation",
    status: "available",
  },
  {
    // Accounting (Phase 24/25) has not started -- no route of its own,
    // and its one existing related capability (Billing, Phase 13)
    // shipped backend only. Both honestly "planned".
    key: "accounting",
    label: "Boekhouding",
    labelEn: "Accounting",
    status: "planned",
    children: [{ key: "billing", label: "Facturatie", labelEn: "Billing", status: "planned" }],
  },
  { key: "reputation", label: "Reputatie", labelEn: "Reputation", segment: "reputation", status: "available" },
  // No standalone AI product page exists yet -- honestly "planned".
  { key: "ai", label: "AI", labelEn: "AI", status: "planned" },
  {
    // Organizational parent -- administrative/product-management
    // functionality, not itself a destination.
    key: "manage",
    label: "Beheer",
    labelEn: "Manage",
    status: "available",
    children: [
      {
        key: "approvals",
        label: "Goedkeuringen",
        labelEn: "Approvals",
        segment: "approvals",
        status: "available",
      },
      { key: "settings", label: "Instellingen", labelEn: "Settings", segment: "settings", status: "available" },
      // Agency-only tenant administration (managing client businesses),
      // not a "Klanten" (CRM/business-customer) concept -- kept
      // distinct so the two are never confused. Visibility of this
      // screen for a given user is decided by the backend's own
      // authorization exactly as before (per ADR-0011, never by a
      // frontend `tenant_type`/`user_type` check) -- a tenant with no
      // clients simply sees an empty list.
      {
        key: "clients",
        label: "Klantbedrijven",
        labelEn: "Client accounts",
        segment: "clients",
        status: "available",
      },
    ],
  },
];
