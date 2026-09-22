// Business-language timestamp formatting for the Unified Inbox
// (docs/ROADMAP.md Phase 30) -- "Vandaag"/"Gisteren" read naturally in an
// inbox list the way a raw ISO timestamp or a generic locale string does
// not.

export function inboxTimestamp(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);

  const time = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (diffDays === 0) return `Vandaag, ${time}`;
  if (diffDays === 1) return `Gisteren, ${time}`;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + `, ${time}`;
}
