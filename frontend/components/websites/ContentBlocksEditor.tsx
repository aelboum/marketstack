"use client";

// Editor for a page's `content_blocks` -- the closed, five-type block
// vocabulary `product/websites/content_blocks.py::BLOCK_TYPES` defines
// and nothing else (no raw HTML block, no rich-text block, no custom
// component block -- that module's own docstring: "a stronger guarantee
// than sanitizing untrusted HTML, because there is no HTML accepted in
// the first place"). A pure controlled list editor -- add/remove/reorder
// and edit each block's own typed fields; saving is the caller's own
// concern (`updatePage()`), not this component's.
import type { ContentBlock } from "@/lib/api/websites";
import { BLOCK_TYPES } from "@/lib/api/websites";
import {
  MAX_BLOCKS_PER_PAGE,
  MAX_HEADING_TEXT_CHARS,
  MAX_PARAGRAPH_TEXT_CHARS,
  MAX_ALT_TEXT_CHARS,
  MAX_ASSET_REF_CHARS,
  MAX_BUTTON_TEXT_CHARS,
  MAX_URL_CHARS,
  MIN_HEADING_LEVEL,
  MAX_HEADING_LEVEL,
} from "@/lib/websites/constraints";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

const BLOCK_LABELS: Record<ContentBlock["type"], string> = {
  heading: "Heading",
  paragraph: "Paragraph",
  image: "Image",
  button: "Button",
  spacer: "Spacer",
};

function defaultBlockFor(type: ContentBlock["type"]): ContentBlock {
  switch (type) {
    case "heading":
      return { type: "heading", text: "", level: 1 };
    case "paragraph":
      return { type: "paragraph", text: "" };
    case "image":
      return { type: "image", asset_ref: "", alt_text: "" };
    case "button":
      return { type: "button", text: "", url: "" };
    case "spacer":
      return { type: "spacer" };
  }
}

function BlockFields({
  block,
  onChange,
}: {
  block: ContentBlock;
  onChange: (block: ContentBlock) => void;
}) {
  const fieldStyle: React.CSSProperties = {
    fontFamily: "inherit",
    fontSize: "var(--font-size-sm)",
    padding: "var(--space-2)",
    border: "1px solid var(--color-border-strong)",
    borderRadius: "var(--radius-sm)",
    width: "100%",
  };

  if (block.type === "heading") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
        <input
          aria-label="Heading text"
          value={block.text}
          maxLength={MAX_HEADING_TEXT_CHARS}
          onChange={(event) => onChange({ ...block, text: event.target.value })}
          style={fieldStyle}
        />
        <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "var(--font-size-xs)" }}>
          Level
          <select
            aria-label="Heading level"
            value={block.level ?? 1}
            onChange={(event) => onChange({ ...block, level: Number(event.target.value) })}
          >
            {Array.from(
              { length: MAX_HEADING_LEVEL - MIN_HEADING_LEVEL + 1 },
              (_, i) => MIN_HEADING_LEVEL + i,
            ).map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
      </div>
    );
  }

  if (block.type === "paragraph") {
    return (
      <textarea
        aria-label="Paragraph text"
        value={block.text}
        maxLength={MAX_PARAGRAPH_TEXT_CHARS}
        rows={3}
        onChange={(event) => onChange({ ...block, text: event.target.value })}
        style={fieldStyle}
      />
    );
  }

  if (block.type === "image") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
        <input
          aria-label="Image asset reference"
          value={block.asset_ref}
          maxLength={MAX_ASSET_REF_CHARS}
          placeholder="Asset reference"
          onChange={(event) => onChange({ ...block, asset_ref: event.target.value })}
          style={fieldStyle}
        />
        <input
          aria-label="Image alt text"
          value={block.alt_text ?? ""}
          maxLength={MAX_ALT_TEXT_CHARS}
          placeholder="Alt text"
          onChange={(event) => onChange({ ...block, alt_text: event.target.value })}
          style={fieldStyle}
        />
      </div>
    );
  }

  if (block.type === "button") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
        <input
          aria-label="Button text"
          value={block.text}
          maxLength={MAX_BUTTON_TEXT_CHARS}
          placeholder="Button text"
          onChange={(event) => onChange({ ...block, text: event.target.value })}
          style={fieldStyle}
        />
        <input
          aria-label="Button URL"
          value={block.url}
          maxLength={MAX_URL_CHARS}
          placeholder="https://…"
          onChange={(event) => onChange({ ...block, url: event.target.value })}
          style={fieldStyle}
        />
      </div>
    );
  }

  // Spacer accepts no fields (`_validate_spacer()`).
  return <p style={{ margin: 0, fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>No configuration.</p>;
}

export function ContentBlocksEditor({
  blocks,
  onChange,
}: {
  blocks: ContentBlock[];
  onChange: (blocks: ContentBlock[]) => void;
}) {
  const atLimit = blocks.length >= MAX_BLOCKS_PER_PAGE;

  function addBlock(type: ContentBlock["type"]) {
    onChange([...blocks, defaultBlockFor(type)]);
  }

  function removeBlock(index: number) {
    onChange(blocks.filter((_, i) => i !== index));
  }

  function moveBlock(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= blocks.length) return;
    const next = [...blocks];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  function updateBlock(index: number, block: ContentBlock) {
    onChange(blocks.map((b, i) => (i === index ? block : b)));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      {blocks.length === 0 ? (
        <p style={{ margin: 0, fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
          No content blocks yet.
        </p>
      ) : (
        <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          {blocks.map((block, index) => (
            <li key={index}>
              <Card>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    flexWrap: "wrap",
                    marginBottom: "var(--space-2)",
                  }}
                >
                  <strong style={{ fontSize: "var(--font-size-sm)" }}>{BLOCK_LABELS[block.type]}</strong>
                  <div style={{ display: "flex", gap: "var(--space-1)" }}>
                    <Button
                      variant="ghost"
                      size="sm"
                      type="button"
                      onClick={() => moveBlock(index, -1)}
                      disabled={index === 0}
                      aria-label={`Move block ${index + 1} up`}
                    >
                      ↑
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      type="button"
                      onClick={() => moveBlock(index, 1)}
                      disabled={index === blocks.length - 1}
                      aria-label={`Move block ${index + 1} down`}
                    >
                      ↓
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      type="button"
                      onClick={() => removeBlock(index)}
                      aria-label={`Remove block ${index + 1}`}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
                <BlockFields block={block} onChange={(updated) => updateBlock(index, updated)} />
              </Card>
            </li>
          ))}
        </ol>
      )}

      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
          Add block
          <select
            aria-label="Block type to add"
            disabled={atLimit}
            defaultValue=""
            onChange={(event) => {
              const type = event.target.value as ContentBlock["type"];
              if (type) addBlock(type);
              event.target.value = "";
            }}
          >
            <option value="" disabled>
              Choose…
            </option>
            {BLOCK_TYPES.map((type) => (
              <option key={type} value={type}>
                {BLOCK_LABELS[type]}
              </option>
            ))}
          </select>
        </label>
        {atLimit ? (
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
            Maximum {MAX_BLOCKS_PER_PAGE} blocks reached.
          </span>
        ) : null}
      </div>
    </div>
  );
}
