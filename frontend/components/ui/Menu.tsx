"use client";

import { useEffect, useId, useRef, useState } from "react";
import styles from "./Menu.module.css";

export type MenuAction = {
  key: string;
  label: string;
  onSelect: () => void;
};

/** Minimal accessible dropdown menu -- closes on outside click, Escape,
 * and item selection; each item is keyboard-reachable (native <button>),
 * and Up/Down/Home/End move roving focus among items per the ARIA menu
 * authoring pattern. */
export function Menu({ trigger, items }: { trigger: React.ReactNode; items: MenuAction[] }) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = useId();

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!open) return;

    itemRefs.current[0]?.focus();

    function handlePointerDown(event: PointerEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        close();
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const focusable = itemRefs.current.filter((node): node is HTMLButtonElement => node !== null);
      if (focusable.length === 0) return;
      const currentIndex = focusable.indexOf(document.activeElement as HTMLButtonElement);
      let nextIndex: number;
      if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = focusable.length - 1;
      else if (event.key === "ArrowDown") nextIndex = (currentIndex + 1) % focusable.length;
      else nextIndex = (currentIndex - 1 + focusable.length) % focusable.length;
      focusable[nextIndex].focus();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div className={styles.wrapper} ref={wrapperRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((value) => !value)}
      >
        {trigger}
      </button>
      {open ? (
        <div id={menuId} role="menu" className={styles.panel}>
          {items.map((item, index) => (
            <button
              key={item.key}
              ref={(node) => {
                itemRefs.current[index] = node;
              }}
              role="menuitem"
              type="button"
              className={styles.item}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
