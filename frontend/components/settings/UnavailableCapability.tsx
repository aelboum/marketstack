"use client";

// The honest rendering of a settings capability this product intends but
// cannot yet perform, because no backend contract exists for it.
//
// UI-7's rule is that a missing API is documented, never invented. This
// component is how that rule looks on screen: it names the capability,
// states plainly that it cannot be configured yet, and -- for whoever is
// reading the UI to decide what backend work to do next -- names the
// exact missing contract. It renders no form, holds no draft state, and
// writes nothing anywhere, so there is no way for it to look like
// persistence that isn't happening.
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function UnavailableCapability({
  title,
  summary,
  missingContract,
  whatExistsToday,
}: {
  title: string;
  /** What the capability would do, in product terms. */
  summary: string;
  /** The exact endpoint(s) that would have to exist. Written for a
   * backend reader, not an end user. */
  missingContract: string[];
  /** What the backend genuinely has today, so the gap is precise rather
   * than an unqualified "not supported". */
  whatExistsToday?: string;
}) {
  return (
    <Card>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          flexWrap: "wrap",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "var(--font-size-md)" }}>{title}</h3>
        {/* Text badge, not a color cue. */}
        <Badge tone="neutral">Not available yet</Badge>
      </div>

      <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-sm)" }}>{summary}</p>

      <InlineNotice tone="warning">
        This cannot be configured yet. No API exists for it, so there is nothing to save — the
        product intentionally shows no form here rather than one that would discard your changes.
      </InlineNotice>

      {whatExistsToday ? (
        <p
          style={{
            margin: "var(--space-3) 0 0",
            fontSize: "var(--font-size-sm)",
            color: "var(--color-text-muted)",
          }}
        >
          {whatExistsToday}
        </p>
      ) : null}

      <details style={{ marginTop: "var(--space-3)" }}>
        <summary style={{ cursor: "pointer", fontSize: "var(--font-size-sm)" }}>
          Required API (for the team building this)
        </summary>
        <ul
          style={{
            margin: "var(--space-2) 0 0",
            paddingLeft: "var(--space-4)",
            fontSize: "var(--font-size-xs)",
            color: "var(--color-text-muted)",
          }}
        >
          {missingContract.map((line) => (
            <li key={line} style={{ wordBreak: "break-word" }}>
              <code>{line}</code>
            </li>
          ))}
        </ul>
      </details>
    </Card>
  );
}
