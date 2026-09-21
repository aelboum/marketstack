// Centralized settings-area configuration, mirroring lib/nav/config.ts's
// own reasoning one level down: `SettingsNavigation` renders from this
// one list, so adding a future settings area is a one-line edit here --
// never a change to the application shell, to `SettingsShell`, or to
// every page that happens to render settings navigation.
//
// `status` exists for the same reason the app-wide nav has
// "available" vs "planned": this product has settings capabilities whose
// backend contract does not exist yet (branding and custom domains are
// the concrete case -- see lib/api/settings.ts's module docstring).
// Listing such an area as "unavailable" states honestly that the product
// intends it and cannot do it yet; omitting it entirely would hide a
// known gap, and marking it "available" would promise a screen that
// cannot persist anything.

export type SettingsAreaStatus =
  /** A real backend contract exists and the page uses it. */
  | "available"
  /** The capability is real product intent, but no HTTP API exists for
   * it yet -- the page must render an explicit not-configurable state
   * and must never fake persistence. */
  | "unavailable";

export type SettingsArea = {
  key: string;
  label: string;
  /** Path segment under `/t/[tenantId]/settings`; omitted for the index. */
  segment?: string;
  description: string;
  status: SettingsAreaStatus;
};

export const SETTINGS_AREAS: SettingsArea[] = [
  {
    key: "general",
    label: "General",
    description: "Tenant identity and workspace details.",
    status: "available",
  },
  {
    key: "branding",
    label: "Branding",
    segment: "branding",
    description: "Logo, colors, and custom domain.",
    // No product API exposes `white_label` branding or domains -- the
    // module ships a service layer and tables but no router, and
    // `product/api/main.py` mounts no white-label routes. See
    // lib/api/settings.ts.
    status: "unavailable",
  },
  {
    key: "profile",
    label: "Profile",
    segment: "profile",
    description: "Your account and session.",
    status: "available",
  },
  {
    key: "access",
    label: "Access",
    segment: "access",
    description: "Teammates and delegated administration.",
    status: "available",
  },
  {
    key: "support-access",
    label: "Support access",
    segment: "support-access",
    description: "Time-boxed access granted to a parent agency.",
    status: "available",
  },
];

export function settingsHref(tenantId: string, area: SettingsArea): string {
  const base = `/t/${tenantId}/settings`;
  return area.segment ? `${base}/${area.segment}` : base;
}
