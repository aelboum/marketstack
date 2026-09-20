import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Menu } from "./Menu";

describe("Menu", () => {
  it("opens on trigger click and each item is keyboard-reachable", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<Menu trigger="Account" items={[{ key: "logout", label: "Log out", onSelect }]} />);

    const trigger = screen.getByRole("button", { name: "Account" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("selecting an item calls onSelect and closes the menu", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<Menu trigger="Account" items={[{ key: "logout", label: "Log out", onSelect }]} />);

    await user.click(screen.getByRole("button", { name: "Account" }));
    await user.click(screen.getByRole("menuitem", { name: "Log out" }));

    expect(onSelect).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
