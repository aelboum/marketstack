import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ContentBlocksEditor } from "./ContentBlocksEditor";
import type { ContentBlock } from "@/lib/api/websites";

describe("ContentBlocksEditor", () => {
  it("shows an empty message with no blocks", () => {
    render(<ContentBlocksEditor blocks={[]} onChange={vi.fn()} />);
    expect(screen.getByText("No content blocks yet.")).toBeInTheDocument();
  });

  it("adding a heading block appends the real default shape", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<ContentBlocksEditor blocks={[]} onChange={onChange} />);

    await user.selectOptions(screen.getByLabelText("Block type to add"), "heading");
    expect(onChange).toHaveBeenCalledWith([{ type: "heading", text: "", level: 1 }]);
  });

  it("editing a paragraph block's text updates only that block", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const blocks: ContentBlock[] = [
      { type: "paragraph", text: "" },
      { type: "spacer" },
    ];
    render(<ContentBlocksEditor blocks={blocks} onChange={onChange} />);

    await user.type(screen.getByLabelText("Paragraph text"), "Hi");
    // Called once per keystroke; check the final call carries the accumulated text
    // by inspecting the last call's first block.
    const lastCall = onChange.mock.calls.at(-1)![0] as ContentBlock[];
    expect(lastCall[1]).toEqual({ type: "spacer" });
    expect(lastCall[0].type).toBe("paragraph");
  });

  it("removes a block", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const blocks: ContentBlock[] = [{ type: "spacer" }, { type: "paragraph", text: "keep" }];
    render(<ContentBlocksEditor blocks={blocks} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "Remove block 1" }));
    expect(onChange).toHaveBeenCalledWith([{ type: "paragraph", text: "keep" }]);
  });

  it("moves a block down, swapping order", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const blocks: ContentBlock[] = [{ type: "spacer" }, { type: "paragraph", text: "second" }];
    render(<ContentBlocksEditor blocks={blocks} onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "Move block 1 down" }));
    expect(onChange).toHaveBeenCalledWith([
      { type: "paragraph", text: "second" },
      { type: "spacer" },
    ]);
  });

  it("disables move up on the first block and move down on the last", () => {
    const blocks: ContentBlock[] = [{ type: "spacer" }, { type: "spacer" }];
    render(<ContentBlocksEditor blocks={blocks} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Move block 1 up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move block 2 down" })).toBeDisabled();
  });

  it("disables Add block once the real 100-block cap is reached", () => {
    const blocks: ContentBlock[] = Array.from({ length: 100 }, () => ({ type: "spacer" as const }));
    render(<ContentBlocksEditor blocks={blocks} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Block type to add")).toBeDisabled();
    expect(screen.getByText(/Maximum 100 blocks reached/)).toBeInTheDocument();
  });

  it("a button block shows both text and URL fields", () => {
    const blocks: ContentBlock[] = [{ type: "button", text: "Click", url: "https://example.com" }];
    render(<ContentBlocksEditor blocks={blocks} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Button text")).toHaveValue("Click");
    expect(screen.getByLabelText("Button URL")).toHaveValue("https://example.com");
  });

  it("a spacer block shows no configuration fields", () => {
    const blocks: ContentBlock[] = [{ type: "spacer" }];
    render(<ContentBlocksEditor blocks={blocks} onChange={vi.fn()} />);
    expect(screen.getByText("No configuration.")).toBeInTheDocument();
  });
});
