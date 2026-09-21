"use client";

// Renders a message body as plain text only -- never
// `dangerouslySetInnerHTML`; React's own text-node rendering already
// escapes everything, so no link/script/markup in a message body is
// ever executed. Long bodies are visually bounded (collapsed behind a
// "Show more" toggle) rather than truncated -- the full content is
// always still there and reachable, never silently discarded.
import { useId, useState } from "react";

const COLLAPSE_THRESHOLD = 600;

export function MessageBody({ body }: { body: string }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = body.length > COLLAPSE_THRESHOLD;
  const bodyId = useId();

  return (
    <div>
      <p
        id={bodyId}
        style={{
          margin: 0,
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
          maxHeight: isLong && !expanded ? "8em" : "none",
          overflow: isLong && !expanded ? "hidden" : "visible",
        }}
      >
        {body}
      </p>
      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-controls={bodyId}
          style={{
            background: "none",
            border: "none",
            color: "var(--color-accent)",
            cursor: "pointer",
            padding: 0,
            fontSize: "var(--font-size-xs)",
            marginTop: "var(--space-1)",
          }}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      ) : null}
    </div>
  );
}
