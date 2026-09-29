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

  it("opening the menu focuses the first item, and arrow keys move roving focus", async () => {
    const user = userEvent.setup();
    render(
      <Menu
        trigger="Account"
        items={[
          { key: "profile", label: "Profile", onSelect: vi.fn() },
          { key: "settings", label: "Settings", onSelect: vi.fn() },
          { key: "logout", label: "Log out", onSelect: vi.fn() },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByRole("menuitem", { name: "Profile" })).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Settings" })).toHaveFocus();

    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Profile" })).toHaveFocus();

    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: "Log out" })).toHaveFocus();

    await user.keyboard("{Home}");
    expect(screen.getByRole("menuitem", { name: "Profile" })).toHaveFocus();

    await user.keyboard("{End}");
    expect(screen.getByRole("menuitem", { name: "Log out" })).toHaveFocus();
  });

  it("Escape closes the menu and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<Menu trigger="Account" items={[{ key: "logout", label: "Log out", onSelect: vi.fn() }]} />);

    const trigger = screen.getByRole("button", { name: "Account" });
    await user.click(trigger);
    await user.keyboard("{Escape}");

    expect(trigger).toHaveFocus();
  });
});
